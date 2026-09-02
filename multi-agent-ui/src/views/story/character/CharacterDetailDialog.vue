<script setup lang="ts">
/**
 * 角色详情对话框：基础信息编辑 + 立绘管理（上传/主立绘/删除）+ 出演项目提示。
 */
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { characterApi, storyFileUrl, type StoryArtType, type StoryCharacterDetailVO, type StoryRoleType } from "@/api/story";
import { confirmDanger } from "@/utils/confirm";
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

// 立绘类型：三视图与正面半身特写为外部视频生成的必备参考图
const ART_TYPE_OPTIONS: { value: StoryArtType; label: string }[] = [
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
const uploadArtType = ref<StoryArtType>("full_body");

// 必备参考图完整性：至少一张三视图 + 至少一张正面半身特写
const hasTurnaround = computed(
  () => detail.value?.arts.some((art) => art.art_type === "turnaround") ?? false
);
const hasFrontBust = computed(
  () => detail.value?.arts.some((art) => art.art_type === "front_bust") ?? false
);

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
    if (!visible || !props.characterId) return;
    // 打开即重置：避免加载期间/失败后渲染上一个角色的陈旧数据
    detail.value = null;
    await loadDetail(props.characterId);
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
    // 加载失败（如角色已被删除）：detail 保持空，模板显示失败空态；
    // 错误提示由响应拦截器统一弹出
    detail.value = null;
  } finally {
    loading.value = false;
  }
}

async function handleSave() {
  if (!props.characterId) return;
  if (!form.name.trim()) {
    ElMessage.error("角色名不能为空");
    return;
  }
  saving.value = true;
  try {
    await characterApi.update(props.characterId, {
      name: form.name.trim(),
      role_type: form.role_type || null,
      appearance_prompt: form.appearance_prompt.trim() || null,
      negative_prompt: form.negative_prompt.trim() || null,
      profile: form.profile,
      style: form.style,
    });
    ElMessage.success("角色已保存");
    emit("changed");
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
  if (!file || !props.characterId) return;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!["png", "jpg", "jpeg", "webp"].includes(ext)) {
    ElMessage.error("仅支持 png/jpg/jpeg/webp 图片");
    return;
  }
  uploading.value = true;
  try {
    await characterApi.uploadArt(props.characterId, file, undefined, uploadArtType.value);
    ElMessage.success("立绘已上传");
    await loadDetail(props.characterId, true);
    emit("changed");
  } finally {
    uploading.value = false;
  }
}

async function handleSetPrimary(artId: string) {
  if (!props.characterId) return;
  await characterApi.setPrimaryArt(props.characterId, artId);
  ElMessage.success("主立绘已更新");
  await loadDetail(props.characterId, true);
  emit("changed");
}

async function handleDeleteArt(artId: string) {
  if (!props.characterId) return;
  const confirmed = await confirmDanger("确定删除这张立绘吗？");
  if (!confirmed) return;
  await characterApi.removeArt(props.characterId, artId);
  ElMessage.success("立绘已删除");
  await loadDetail(props.characterId, true);
  emit("changed");
}
</script>

<template>
  <el-dialog v-model="dialogVisible" title="角色详情" width="920px" destroy-on-close>
    <div v-loading="loading" class="character-detail">
      <template v-if="detail">
        <div class="detail-layout">
          <!-- 左：基础信息 -->
          <el-form label-width="96px" class="detail-form">
            <div class="detail-head">
              <el-avatar :size="72" :src="storyFileUrl(detail.avatar_file) || undefined">
                {{ detail.name.slice(0, 1) }}
              </el-avatar>
              <div class="detail-head-meta">
                <div class="detail-name">
                  {{ detail.name }}
                  <el-tag v-if="detail.role_type" size="small" type="info">
                    {{ ROLE_LABEL[detail.role_type] ?? detail.role_type }}
                  </el-tag>
                </div>
                <div class="detail-sub">立绘 {{ detail.arts.length }} 张</div>
              </div>
            </div>
            <el-form-item label="角色名">
              <el-input v-model="form.name" maxlength="100" />
            </el-form-item>
            <el-form-item label="角色分类">
              <el-select v-model="form.role_type" clearable placeholder="未设置">
                <el-option
                  v-for="option in ROLE_TYPE_OPTIONS"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="外观描述">
              <el-input v-model="form.appearance_prompt" type="textarea" :rows="3" />
            </el-form-item>
            <el-form-item label="负向提示词">
              <el-input v-model="form.negative_prompt" type="textarea" :rows="2" />
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
              <el-button type="primary" :loading="saving" @click="handleSave">保存资料</el-button>
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
              <div class="upload-controls">
                <el-select v-model="uploadArtType" size="small" class="art-type-select">
                  <el-option
                    v-for="option in ART_TYPE_OPTIONS"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
                <el-button size="small" :loading="uploading" @click="openArtPicker">上传立绘</el-button>
              </div>
            </div>
            <div class="required-arts">
              <el-tag size="small" :type="hasTurnaround ? 'success' : 'warning'">
                三视图 {{ hasTurnaround ? "已具备" : "缺失" }}
              </el-tag>
              <el-tag size="small" :type="hasFrontBust ? 'success' : 'warning'">
                正面半身特写 {{ hasFrontBust ? "已具备" : "缺失" }}
              </el-tag>
              <span v-if="!hasTurnaround || !hasFrontBust" class="required-hint">
                外部视频生成建议至少各备一张
              </span>
            </div>
            <div v-if="detail.arts.length" class="art-grid">
              <div v-for="art in detail.arts" :key="art.id" class="art-item">
                <el-image :src="storyFileUrl(art.image_file)" fit="cover" class="art-image" />
                <el-tag v-if="art.is_primary" class="art-badge" size="small" type="warning">主立绘</el-tag>
                <div class="art-name">{{ art.name || "未命名" }}</div>
                <div class="art-type">{{ ART_TYPE_LABEL[art.art_type] ?? art.art_type }}</div>
                <div class="art-actions">
                  <el-button v-if="!art.is_primary" size="small" link @click="handleSetPrimary(art.id)">
                    设为主立绘
                  </el-button>
                  <el-button size="small" link type="danger" @click="handleDeleteArt(art.id)">删除</el-button>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无立绘，上传首张将自动成为主立绘" :image-size="80" />

            <div class="side-head casting-head">
              <span class="side-title">出演项目</span>
            </div>
            <div v-if="detail.casting_projects.length" class="casting-list">
              <el-tag v-for="project in detail.casting_projects" :key="project.project_id" class="casting-tag">
                {{ project.title }}
              </el-tag>
            </div>
            <div v-else class="casting-empty">尚未被任何项目出演</div>
          </div>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="角色加载失败或已不存在" :image-size="90" />
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
  width: 130px;
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
