<script setup lang="ts">
/**
 * 角色编辑/新建页面：独立完整页面，便于资料修改与立绘浏览管理。
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { ArrowLeft, Check, Plus, UploadFilled } from "@element-plus/icons-vue";
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

const route = useRoute();
const router = useRouter();

// 支持 /story/character/edit/:id 或 /story/character/edit?id=xxx
const currentId = ref<string | null>(
  (route.params.id as string) || (route.query.id as string) || null
);

const isCreate = computed(() => !currentId.value);
const pageTitle = computed(() => (isCreate.value ? "新建角色" : `编辑角色 - ${form.name || "未命名"}`));

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

const ART_TYPE_OPTIONS: { value: StoryArtType; label: string }[] = [
  { value: "character_sheet", label: "主视图+三视图" },
  { value: "full_body", label: "全身" },
  { value: "half_body", label: "半身" },
  { value: "face", label: "面部特写" },
  { value: "action", label: "动作" },
  { value: "reference", label: "参考图" },
  { value: "other", label: "其他" },
];
const ART_TYPE_LABEL: Record<string, string> = {
  turnaround: "三视图",
  front_bust: "主视图",
  ...Object.fromEntries(ART_TYPE_OPTIONS.map((item) => [item.value, item.label])),
};

const loading = ref(false);
const saving = ref(false);
const uploading = ref(false);
const detail = ref<StoryCharacterDetailVO | null>(null);
const uploadArtType = ref<StoryArtType>("character_sheet");

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

async function loadDetail(characterId: string, keepForm = false) {
  loading.value = true;
  try {
    const res = await characterApi.detail(characterId);
    detail.value = res.data;
    if (!keepForm && res.data) {
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

function initData() {
  const charId = (route.params.id as string) || (route.query.id as string) || null;
  currentId.value = charId;
  detail.value = null;
  uploadArtType.value = "character_sheet";
  formRef.value?.clearValidate();

  if (charId) {
    loadDetail(charId);
  } else {
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

onMounted(initData);

watch(
  () => [route.params.id, route.query.id],
  () => {
    initData();
  }
);

function goBack() {
  router.push("/story/character");
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
      ElMessage.success("角色创建成功");
      if (res.data?.id) {
        currentId.value = res.data.id;
        // 更新路由路径为编辑态，支持刷新与深链接
        router.replace({ path: "/story/character/edit", query: { id: res.data.id } });
        await loadDetail(res.data.id);
      } else {
        goBack();
      }
    } else {
      if (!currentId.value) return;
      await characterApi.update(currentId.value, payload);
      ElMessage.success("角色资料已保存");
      await loadDetail(currentId.value, true);
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
  const defaultName = file.name.replace(/\.[^/.]+$/, "").trim() || file.name;
  uploading.value = true;
  try {
    await characterApi.uploadArt(currentId.value, file, defaultName, uploadArtType.value);
    ElMessage.success("立绘已成功上传");
    await loadDetail(currentId.value, true);
  } finally {
    uploading.value = false;
  }
}

async function handleSetPrimary(artId: string) {
  if (!currentId.value) return;
  await characterApi.setPrimaryArt(currentId.value, artId);
  ElMessage.success("主立绘已更新");
  await loadDetail(currentId.value, true);
}

async function handleDeleteArt(artId: string) {
  if (!currentId.value) return;
  const confirmed = await confirmDanger("确定删除这张立绘吗？");
  if (!confirmed) return;
  await characterApi.removeArt(currentId.value, artId);
  ElMessage.success("立绘已删除");
  await loadDetail(currentId.value, true);
}
</script>

<template>
  <div class="character-edit-page list-page">
    <!-- 顶部状态栏与操作 -->
    <div class="page-topbar">
      <div class="topbar-left">
        <el-button :icon="ArrowLeft" text class="back-btn" @click="goBack">返回角色库</el-button>
        <el-divider direction="vertical" />
        <div class="title-group">
          <h2 class="page-title">{{ pageTitle }}</h2>
          <el-tag v-if="form.role_type" size="small" type="info" class="role-tag">
            {{ dictStore.getLabel("story_role_type", form.role_type) || (ROLE_LABEL[form.role_type] ?? form.role_type) }}
          </el-tag>
        </div>
      </div>
      <div class="topbar-right">
        <el-button @click="goBack">取消</el-button>
        <el-button type="primary" :icon="Check" :loading="saving" @click="handleSave">
          {{ isCreate ? "创建角色" : "保存修改" }}
        </el-button>
      </div>
    </div>

    <!-- 主体编辑区（两栏布局） -->
    <div v-loading="loading" class="edit-content-container">
      <div class="edit-grid">
        <!-- 左侧：基础人设与提示词 -->
        <div class="section-card form-section">
          <div class="section-header">
            <div class="section-title">基础档案</div>
            <span class="section-sub">角色名称、外貌特征设定与视觉控制词</span>
          </div>

          <div class="character-hero">
            <el-avatar
              :size="80"
              :src="detail?.avatar_file ? storyFileUrl(detail.avatar_file) : undefined"
              class="hero-avatar"
            >
              {{ form.name ? form.name.slice(0, 1) : (isCreate ? "+" : "?") }}
            </el-avatar>
            <div class="hero-info">
              <div class="hero-name">{{ form.name || (isCreate ? "新角色" : "未命名") }}</div>
              <div class="hero-desc">
                <template v-if="!isCreate && detail">
                  已关联立绘 {{ detail.arts.length }} 张 · 出演项目 {{ detail.casting_projects?.length || 0 }} 个
                </template>
                <template v-else>
                  完善基础信息并保存后，即可上传三视图与立绘
                </template>
              </div>
            </div>
          </div>

          <el-form
            ref="formRef"
            :model="form"
            :rules="formRules"
            label-position="top"
            class="main-form"
          >
            <el-row :gutter="16">
              <el-col :span="14">
                <el-form-item label="角色名" prop="name" required>
                  <el-input
                    v-model="form.name"
                    maxlength="100"
                    show-word-limit
                    placeholder="如：林晚 / 陆辰"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="10">
                <el-form-item label="角色分类">
                  <el-select
                    v-model="form.role_type"
                    clearable
                    placeholder="默认分类（跨项目可不同）"
                    style="width: 100%"
                  >
                    <el-option
                      v-for="option in roleOptions"
                      :key="option.value"
                      :label="option.label"
                      :value="option.value"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="外貌描述（Prompt）">
              <el-input
                v-model="form.appearance_prompt"
                type="textarea"
                :rows="4"
                placeholder="供生图模型复用的外观提示词，如：黑发少年，琥珀色眼睛，修长身材，身穿深蓝色立领风衣，神情清冷…"
              />
              <div class="field-hint">用于生成剧本分镜关键帧时对该角色的外貌一致性约束。</div>
            </el-form-item>

            <el-form-item label="负向提示词（Negative Prompt）">
              <el-input
                v-model="form.negative_prompt"
                type="textarea"
                :rows="2"
                placeholder="可选。针对该角色生成时需规避的元素，如：眼镜，胡须，现代服饰等…"
              />
            </el-form-item>

            <el-form-item label="人设属性（Profile）">
              <KeyValueEditor
                v-model="form.profile"
                key-placeholder="属性项，如：性格 / 年龄 / 身份"
                value-placeholder="设定内容，如：坚毅内敛 / 22岁"
              />
            </el-form-item>

            <el-form-item label="视觉风格（Style）">
              <KeyValueEditor
                v-model="form.style"
                key-placeholder="风格项，如：画风 / 服饰风格"
                value-placeholder="设定内容，如：新海诚光影 / 赛博朋克机能风"
              />
            </el-form-item>

            <div class="form-bottom-actions">
              <el-button type="primary" :icon="Check" :loading="saving" @click="handleSave">
                {{ isCreate ? "创建并管理立绘" : "保存修改" }}
              </el-button>
            </div>
          </el-form>
        </div>

        <!-- 右侧：立绘库与出演项目 -->
        <div class="section-card art-section">
          <div class="section-header">
            <div class="section-title">角色立绘</div>
            <span class="section-sub">支持主视图、三视图及多视角参考立绘</span>
          </div>

          <!-- 隐藏的文件上传原生 input -->
          <input
            ref="artInput"
            type="file"
            accept=".png,.jpg,.jpeg,.webp"
            style="display: none"
            @change="onArtPicked"
          />

          <template v-if="!isCreate">
            <!-- 上传控制栏 -->
            <div class="art-toolbar">
              <div class="art-status-tags">
                <template v-if="hasCharacterSheet">
                  <el-tag size="small" type="success" effect="plain">主视图+三视图 已具备</el-tag>
                </template>
                <template v-else-if="hasTurnaround && hasFrontBust">
                  <el-tag size="small" type="success" effect="plain">三视图 已具备</el-tag>
                  <el-tag size="small" type="success" effect="plain">主视图 已具备</el-tag>
                </template>
                <template v-else>
                  <el-tag size="small" type="warning" effect="plain">主视图+三视图 缺失</el-tag>
                </template>
              </div>

              <div class="upload-bar">
                <el-select v-model="uploadArtType" size="default" class="art-type-selector">
                  <el-option
                    v-for="option in ART_TYPE_OPTIONS"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
                <el-button
                  type="primary"
                  :icon="UploadFilled"
                  :loading="uploading"
                  @click="openArtPicker"
                >
                  上传立绘
                </el-button>
              </div>
            </div>

            <div v-if="!hasCompleteArt" class="art-tip-box">
              💡 建议上传一张包含【主视图+三视图】的设定图，或者分别上传正面主图与三视图，便于后续生图模型获得最稳定的一致性参考。
            </div>

            <!-- 立绘卡片网格 -->
            <div v-if="detail?.arts?.length" class="art-grid">
              <div
                v-for="(art, artIdx) in detail.arts"
                :key="art.id"
                class="art-card"
                :class="{ 'is-primary': art.is_primary }"
              >
                <div class="art-img-wrapper">
                  <el-image
                    :src="storyFileUrl(art.image_file)"
                    :preview-src-list="detail.arts.map((a) => storyFileUrl(a.image_file))"
                    :initial-index="artIdx"
                    preview-teleported
                    fit="cover"
                    class="art-img"
                  />
                  <span v-if="art.is_primary" class="primary-badge">主立绘</span>
                </div>
                <div class="art-meta">
                  <div class="art-title" :title="art.name || '未命名'">{{ art.name || "未命名" }}</div>
                  <div class="art-badge-row">
                    <el-tag size="small" type="info">{{ ART_TYPE_LABEL[art.art_type] ?? art.art_type }}</el-tag>
                  </div>
                </div>
                <div class="art-card-footer">
                  <el-button
                    v-if="!art.is_primary"
                    size="small"
                    link
                    type="primary"
                    @click="handleSetPrimary(art.id)"
                  >
                    设为主立绘
                  </el-button>
                  <span v-else class="primary-text">当前主立绘</span>
                  <el-button size="small" link type="danger" @click="handleDeleteArt(art.id)">
                    删除
                  </el-button>
                </div>
              </div>
            </div>
            <div v-else class="art-empty-box">
              <el-empty description="暂无立绘，上传的首张立绘将自动设为主立绘" :image-size="100">
                <el-button type="primary" :icon="Plus" :loading="uploading" @click="openArtPicker">
                  立即上传立绘
                </el-button>
              </el-empty>
            </div>

            <!-- 出演项目 -->
            <div class="casting-section">
              <div class="casting-title">出演项目（{{ detail?.casting_projects?.length || 0 }}）</div>
              <div v-if="detail?.casting_projects?.length" class="casting-tags">
                <el-tag
                  v-for="project in detail.casting_projects"
                  :key="project.project_id"
                  effect="light"
                  class="project-tag"
                >
                  🎬 {{ project.title }}
                </el-tag>
              </div>
              <div v-else class="casting-empty-text">该角色尚未被任何项目选入出演。</div>
            </div>
          </template>

          <template v-else>
            <div class="create-art-placeholder">
              <el-empty description="创建角色后即可上传并管理立绘" :image-size="110">
                <div class="placeholder-tip">
                  请先在左侧输入角色名称并点击「创建并管理立绘」，保存后本区域将立即解锁。
                </div>
              </el-empty>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.character-edit-page {
  padding: 16px 24px 32px;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.page-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #fff;
  border: 1px solid #e5e9f2;
  border-radius: 8px;
  margin-bottom: 16px;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  font-size: 14px;
}

.title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #1f2d3d;
}

.role-tag {
  font-weight: normal;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.edit-content-container {
  flex: 1;
}

.edit-grid {
  display: grid;
  grid-template-columns: minmax(460px, 1.15fr) minmax(420px, 1fr);
  gap: 20px;
  align-items: start;
}

.section-card {
  background: #fff;
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  padding: 20px 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.section-header {
  margin-bottom: 18px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f2f5;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2d3d;
}

.section-sub {
  font-size: 12px;
  color: #7d879a;
  margin-top: 4px;
  display: inline-block;
}

.character-hero {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 8px;
  margin-bottom: 20px;
}

.hero-avatar {
  background: #409eff;
  color: #fff;
  font-size: 28px;
  font-weight: bold;
  flex-shrink: 0;
}

.hero-info {
  flex: 1;
  min-width: 0;
}

.hero-name {
  font-size: 16px;
  font-weight: 600;
  color: #1f2d3d;
  margin-bottom: 4px;
}

.hero-desc {
  font-size: 12px;
  color: #7d879a;
}

.main-form :deep(.el-form-item__label) {
  font-weight: 500;
  color: #374151;
  padding-bottom: 6px;
}

.field-hint {
  font-size: 12px;
  color: #9aa4b2;
  margin-top: 4px;
  line-height: 1.4;
}

.form-bottom-actions {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}

/* 右侧立绘管理 */
.art-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.art-status-tags {
  display: flex;
  gap: 8px;
  align-items: center;
}

.upload-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.art-type-selector {
  width: 130px;
}

.art-tip-box {
  padding: 10px 14px;
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 6px;
  font-size: 12px;
  color: #e6a23c;
  line-height: 1.5;
  margin-bottom: 16px;
}

.art-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px;
  margin-bottom: 24px;
}

.art-card {
  border: 1px solid #e5e9f2;
  border-radius: 8px;
  overflow: hidden;
  background: #fafbfd;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
}

.art-card:hover {
  border-color: #b3d8ff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.art-card.is-primary {
  border-color: #f7ba2a;
}

.art-img-wrapper {
  position: relative;
  width: 100%;
  padding-top: 100%;
  background: #f1f3f7;
  overflow: hidden;
}

.art-img {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

.primary-badge {
  position: absolute;
  top: 6px;
  left: 6px;
  background: #e6a23c;
  color: #fff;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.art-meta {
  padding: 8px 10px 4px;
  flex: 1;
}

.art-title {
  font-size: 13px;
  font-weight: 500;
  color: #2c3e50;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.art-badge-row {
  margin-top: 4px;
}

.art-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px 8px;
  border-top: 1px solid #f0f2f5;
  background: #fff;
}

.primary-text {
  font-size: 12px;
  color: #e6a23c;
  font-weight: 500;
}

.art-empty-box {
  padding: 24px 0;
}

.casting-section {
  border-top: 1px solid #f0f2f5;
  padding-top: 18px;
  margin-top: 10px;
}

.casting-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
  margin-bottom: 10px;
}

.casting-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.project-tag {
  font-size: 12px;
}

.casting-empty-text {
  font-size: 12px;
  color: #9aa4b2;
}

.create-art-placeholder {
  padding: 40px 0;
}

.placeholder-tip {
  margin-top: 10px;
  font-size: 13px;
  color: #7d879a;
  max-width: 320px;
  line-height: 1.5;
}

@media (max-width: 1080px) {
  .edit-grid {
    grid-template-columns: 1fr;
  }
}
</style>
