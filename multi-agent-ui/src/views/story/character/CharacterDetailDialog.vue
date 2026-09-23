<script setup lang="ts">
/**
 * 角色详情/编辑/新建对话框：
 * 基础信息编辑 + 立绘管理（上传/设为主立绘/删除）+ 出演项目提示。
 * 支持新建与编辑共用同一个完整对话框，立绘类型默认支持单图包含「半身正面+三视图」。
 */
import { computed, reactive, ref, watch } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import {
  characterApi,
  storyFileUrl,
  type StoryArtType,
  type StoryCharacterDetailVO,
  type StoryCharacterPayload,
  type StoryRoleType,
} from "@/api/story";
import { confirmDanger } from "@/utils/confirm";
import { useDictStore } from "@/stores/dictStore";
import KeyValueEditor from "./KeyValueEditor.vue";

const props = defineProps<{
  visible: boolean;
  characterId: string | null;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "changed"): void;
}>();

const dialogVisible = computed({
  get: () => props.visible,
  set: (value) => emit("update:visible", value),
});

// 内部当前角色 ID（新建成功后回填，使弹窗直接切为详情态供用户上传立绘）
const currentId = ref<string | null>(null);
const isCreate = computed(() => !currentId.value);
const dialogTitle = computed(() => (isCreate.value ? "新建角色" : "角色详情"));

const dictStore = useDictStore();
dictStore.ensureLoaded();

const ROLE_TYPE_OPTIONS: { value: StoryRoleType; label: string }[] = [
  { value: "protagonist", label: "主角" },
  { value: "supporting", label: "配角" },
  { value: "antagonist", label: "反派" },
  { value: "npc", label: "NPC" },
  { value: "other", label: "其他" },
];
const ROLE_LABEL: Record<string, string> = Object.fromEntries(
  ROLE_TYPE_OPTIONS.map((item) => [item.value, item.label])
);

const roleOptions = computed(() => {
  const options = dictStore.getOptions("story_role_type");
  if (options && options.length > 0) return options;
  return ROLE_TYPE_OPTIONS;
});

// 立绘类型：默认单图包含半身正面与三视图；亦兼容分立的三视图与正面半身特写
const ART_TYPE_OPTIONS: { value: StoryArtType; label: string }[] = [
  { value: "character_sheet", label: "半身正面+三视图" },
  { value: "turnaround", label: "三视图" },
  { value: "front_bust", label: "正面半身特写" },
  { value: "full_body", label: "全身" },
  { value: "half_body", label: "半身" },
  { value: "face", label: "面部特写" },
  { value: "action", label: "动作" },
  { value: "reference", label: "参考图" },
  { value: "other", label: "其他" },
];
const ART_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  ART_TYPE_OPTIONS.map((item) => [item.value, item.label])
);

const loading = ref(false);
const saving = ref(false);
const uploading = ref(false);
const detail = ref<StoryCharacterDetailVO | null>(null);
const uploadArtType = ref<StoryArtType>("character_sheet");

// 必备参考图完整性：优先单图包含（半身正面+三视图），亦支持分别具备三视图与正面半身特写
const hasCharacterSheet = computed(
  () => detail.value?.arts.some((art) => art.art_type === "character_sheet") ?? false
);
const hasTurnaround = computed(
  () => detail.value?.arts.some((art) => art.art_type === "turnaround") ?? false
);
const hasFrontBust = computed(
  () => detail.value?.arts.some((art) => art.art_type === "front_bust") ?? false
);
const hasCompleteArt = computed(
  () => hasCharacterSheet.value || (hasTurnaround.value && hasFrontBust.value)
);

const formRef = ref<FormInstance>();
const formRules = computed<FormRules>(() => ({
  name: [{ required: true, message: "请输入角色名", trigger: "blur" }],
}));

const form = reactive({
  name: "",
  role_type: "" as StoryRoleType | "",
  appearance_prompt: "",
  negative_prompt: "",
  profile: {} as Record<string, unknown>,
  style: {} as Record<string, unknown>,
});

watch(
  () => props.visible,
  async (visible) => {
    if (!visible) return;
    currentId.value = props.characterId;
    detail.value = null;
    formRef.value?.clearValidate();
    if (props.characterId) {
      await loadDetail(props.characterId);
    } else {
      // 新建模式重置表单
      Object.assign(form, {
        name: "",
        role_type: "",
        appearance_prompt: "",
        negative_prompt: "",
        profile: {},
        style: {},
      });
    }
  }
);

async function loadDetail(characterId: string, keepForm = false) {
  loading.value = true;
  try {
    const res = await characterApi.detail(characterId);
    detail.value = res.data;
    // keepForm：立绘等操作后的刷新不覆盖用户未保存的资料编辑
    if (!keepForm) {
      const record = res.data;
      Object.assign(form, {
        name: record.name,
        role_type: record.role_type ?? "",
        appearance_prompt: record.appearance_prompt ?? "",
        negative_prompt: record.negative_prompt ?? "",
        profile: { ...record.profile },
        style: { ...record.style },
      });
    }
  } catch {
    detail.value = null;
  } finally {
    loading.value = false;
  }
}

async function handleSave() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;

  const payload: StoryCharacterPayload = {
    name: form.name.trim(),
    role_type: form.role_type || null,
    appearance_prompt: form.appearance_prompt.trim() || null,
    negative_prompt: form.negative_prompt.trim() || null,
    profile: form.profile,
    style: form.style,
  };

  saving.value = true;
  try {
    if (isCreate.value) {
      const res = await characterApi.create(payload);
      ElMessage.success("角色已创建");
      emit("changed");
      if (res.data?.id) {
        currentId.value = res.data.id;
        await loadDetail(res.data.id);
      } else {
        dialogVisible.value = false;
      }
    } else {
      if (!currentId.value) return;
      await characterApi.update(currentId.value, payload);
      ElMessage.success("角色已保存");
      await loadDetail(currentId.value, true);
      emit("changed");
    }
  } finally {
    saving.value = false;
  }
}

// —— 立绘管理 ——
const artInput = ref<HTMLInputElement>();

function openArtPicker() {
  artInput.value?.click();
}

async function onArtPicked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || !currentId.value) return;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!["png", "jpg", "jpeg", "webp"].includes(ext)) {
    ElMessage.error("仅支持 png/jpg/jpeg/webp 图片");
    return;
  }
  // 使用原图片文件名（去除扩展名）作为立绘名称
  const defaultName = file.name.replace(/\.[^/.]+$/, "").trim() || file.name;
  uploading.value = true;
  try {
    await characterApi.uploadArt(currentId.value, file, defaultName, uploadArtType.value);
    ElMessage.success("立绘已上传");
    await loadDetail(currentId.value, true);
    emit("changed");
  } finally {
    uploading.value = false;
  }
}

async function handleSetPrimary(artId: string) {
  if (!currentId.value) return;
  await characterApi.setPrimaryArt(currentId.value, artId);
  ElMessage.success("主立绘已更新");
  await loadDetail(currentId.value, true);
  emit("changed");
}

async function handleDeleteArt(artId: string) {
  if (!currentId.value) return;
  const confirmed = await confirmDanger("确定删除这张立绘吗？");
  if (!confirmed) return;
  await characterApi.removeArt(currentId.value, artId);
  ElMessage.success("立绘已删除");
  await loadDetail(currentId.value, true);
  emit("changed");
}
</script>

<template>
  <el-dialog v-model="dialogVisible" :title="dialogTitle" width="920px" destroy-on-close>
    <div v-loading="loading" class="character-detail">
      <div class="detail-layout">
        <!-- 左：基础信息 -->
        <el-form ref="formRef" :model="form" :rules="formRules" label-width="96px" class="detail-form">
          <div class="detail-head">
            <el-avatar
              :size="72"
              :src="detail?.avatar_file ? storyFileUrl(detail.avatar_file) : undefined"
            >
              {{ form.name ? form.name.slice(0, 1) : (isCreate ? "+" : "?") }}
            </el-avatar>
            <div class="detail-head-meta">
              <div class="detail-name">
                {{ form.name || (isCreate ? "新角色" : "未命名") }}
                <el-tag v-if="form.role_type" size="small" type="info">
                  {{ dictStore.getLabel("story_role_type", form.role_type) || (ROLE_LABEL[form.role_type] ?? form.role_type) }}
                </el-tag>
              </div>
              <div class="detail-sub">
                <template v-if="!isCreate && detail">
                  立绘 {{ detail.arts.length }} 张
                </template>
                <template v-else>
                  填写角色人设，保存后即可管理立绘
                </template>
              </div>
            </div>
          </div>
          <el-form-item label="角色名" prop="name">
            <el-input v-model="form.name" maxlength="100" placeholder="如：林晚" />
          </el-form-item>
          <el-form-item label="角色分类">
            <el-select v-model="form.role_type" clearable placeholder="默认分类（跨项目可不同）">
              <el-option
                v-for="option in roleOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="外观描述">
            <el-input
              v-model="form.appearance_prompt"
              type="textarea"
              :rows="3"
              placeholder="供生图模型复用的外观描述，如：黑发少年，琥珀色眼睛…"
            />
          </el-form-item>
          <el-form-item label="负向提示词">
            <el-input v-model="form.negative_prompt" type="textarea" :rows="2" placeholder="可选" />
          </el-form-item>
          <el-form-item label="人设">
            <KeyValueEditor
              v-model="form.profile"
              key-placeholder="项，如：性格"
              value-placeholder="内容，如：坚毅"
            />
          </el-form-item>
          <el-form-item label="视觉风格">
            <KeyValueEditor
              v-model="form.style"
              key-placeholder="项，如：画风"
              value-placeholder="内容，如：手绘"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="handleSave">
              {{ isCreate ? "创建角色" : "保存资料" }}
            </el-button>
            <el-button @click="dialogVisible = false">关闭</el-button>
          </el-form-item>
        </el-form>

        <!-- 右：立绘与出演 -->
        <div class="detail-side">
          <div class="side-head">
            <span class="side-title">立绘</span>
            <input
              ref="artInput"
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              style="display: none"
              @change="onArtPicked"
            />
            <div v-if="!isCreate" class="upload-controls">
              <el-select v-model="uploadArtType" size="small" class="art-type-select">
                <el-option
                  v-for="option in ART_TYPE_OPTIONS"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-button size="small" :loading="uploading" @click="openArtPicker">
                上传立绘
              </el-button>
            </div>
          </div>

          <template v-if="!isCreate">
            <div class="required-arts">
              <template v-if="hasCharacterSheet">
                <el-tag size="small" type="success">半身正面+三视图 已具备</el-tag>
              </template>
              <template v-else-if="hasTurnaround && hasFrontBust">
                <el-tag size="small" type="success">三视图 已具备</el-tag>
                <el-tag size="small" type="success">正面半身特写 已具备</el-tag>
              </template>
              <template v-else>
                <el-tag size="small" :type="hasTurnaround ? 'success' : 'warning'">
                  三视图 {{ hasTurnaround ? "已具备" : "缺失" }}
                </el-tag>
                <el-tag size="small" :type="hasFrontBust ? 'success' : 'warning'">
                  正面半身特写 {{ hasFrontBust ? "已具备" : "缺失" }}
                </el-tag>
              </template>
              <span v-if="!hasCompleteArt" class="required-hint">
                建议上传一张包含【半身正面+三视图】的设定图
              </span>
            </div>

            <div v-if="detail?.arts?.length" class="art-grid">
              <div v-for="(art, artIdx) in detail.arts" :key="art.id" class="art-item">
                <el-image
                  :src="storyFileUrl(art.image_file)"
                  :preview-src-list="detail.arts.map((a) => storyFileUrl(a.image_file))"
                  :initial-index="artIdx"
                  preview-teleported
                  fit="cover"
                  class="art-image"
                />
                <el-tag v-if="art.is_primary" class="art-badge" size="small" type="warning">
                  主立绘
                </el-tag>
                <div class="art-name">{{ art.name || "未命名" }}</div>
                <div class="art-type">{{ ART_TYPE_LABEL[art.art_type] ?? art.art_type }}</div>
                <div class="art-actions">
                  <el-button
                    v-if="!art.is_primary"
                    size="small"
                    link
                    @click="handleSetPrimary(art.id)"
                  >
                    设为主立绘
                  </el-button>
                  <el-button size="small" link type="danger" @click="handleDeleteArt(art.id)">
                    删除
                  </el-button>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无立绘，上传首张将自动成为主立绘" :image-size="80" />

            <div class="side-head casting-head">
              <span class="side-title">出演项目</span>
            </div>
            <div v-if="detail?.casting_projects?.length" class="casting-list">
              <el-tag
                v-for="project in detail.casting_projects"
                :key="project.project_id"
                class="casting-tag"
              >
                {{ project.title }}
              </el-tag>
            </div>
            <div v-else class="casting-empty">尚未被任何项目出演</div>
          </template>

          <template v-else>
            <el-empty description="创建角色后即可上传与管理立绘" :image-size="80" />
            <div class="side-head casting-head">
              <span class="side-title">出演项目</span>
            </div>
            <div class="casting-empty">新角色尚未被任何项目出演</div>
          </template>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.character-detail {
  min-height: 320px;
}
.detail-layout {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 20px;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.detail-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #1f2d3d;
}
.detail-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #7d879a;
}
.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.upload-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}
.art-type-select {
  width: 140px;
}
.required-arts {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.required-hint {
  font-size: 12px;
  color: #9aa4b2;
}
.casting-head {
  margin-top: 18px;
}
.side-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.art-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 10px;
}
.art-item {
  position: relative;
  border: 1px solid #e5e9f2;
  border-radius: 8px;
  overflow: hidden;
  background: #fafbfd;
}
.art-image {
  width: 100%;
  height: 120px;
  display: block;
}
.art-badge {
  position: absolute;
  top: 6px;
  left: 6px;
}
.art-name {
  padding: 6px 8px 0;
  font-size: 12px;
  color: #4b5563;
}
.art-type {
  padding: 0 8px;
  font-size: 11px;
  color: #9aa4b2;
}
.art-actions {
  display: flex;
  justify-content: space-between;
  padding: 2px 4px 4px;
}
.casting-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.casting-empty {
  font-size: 12px;
  color: #9aa4b2;
}
</style>
