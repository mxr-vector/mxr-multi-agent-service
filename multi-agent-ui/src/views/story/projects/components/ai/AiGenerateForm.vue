<script setup lang="ts">
/**
 * 现代化 AI 生成表单：支持剧本创作与图像生成（立绘/关键帧/场景），
 * 支持「创建图片」单点切换常亮模式，圆角现代化 UI 风格；
 * 支持通用文档解析与拖拽/粘贴。
 */
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { Paperclip, Picture, Promotion } from "@element-plus/icons-vue";
import type { StoryGeneratePayload, StoryStyleVO } from "@/api/story";
import {
  commonFileApi,
  COMMON_FILE_ACCEPT,
  COMMON_FILE_EXTENSIONS,
  validateCommonFile,
} from "@/api/common";
import { useDictStore } from "@/stores/dictStore";

export interface CharacterPromptOption {
  id: string;
  name: string;
  art_prompt?: string | null;
  message_id?: string;
}

const form = defineModel<StoryGeneratePayload>({ required: true });

const props = withDefaults(
  defineProps<{
    styles: StoryStyleVO[];
    generating: boolean;
    generatingArt?: boolean;
    characters?: CharacterPromptOption[];
  }>(),
  {
    generatingArt: false,
    characters: () => [],
  }
);

const emit = defineEmits<{
  (e: "send"): void;
  (e: "stop"): void;
  (
    e: "generateArt",
    payload: {
      prompt: string;
      name?: string;
      cardMessageId?: string;
      size?: string;
      quality?: string;
    }
  ): void;
}>();

// —— 生图模式状态（点击「创建图片」后常亮） ——
const isImageMode = ref(false);

function toggleImageMode() {
  isImageMode.value = !isImageMode.value;
  if (isImageMode.value) {
    ElMessage.info("已切换为生图模式，点击「生成图片」将直接调用图像生成模型");
  }
}

// —— 文件上传与解析 ——
const parsingFile = ref(false);

async function handleFileUpload(rawFile: File) {
  const err = validateCommonFile(rawFile);
  if (err) {
    ElMessage.error(err);
    return false;
  }
  parsingFile.value = true;
  try {
    const res = await commonFileApi.parse(rawFile);
    const parsed = res.data;
    if (!parsed?.content) {
      ElMessage.warning(`文档「${rawFile.name}」解析结果为空`);
      return false;
    }
    const header = `【参考文档：${parsed.filename}】\n`;
    if (!form.value.idea || !form.value.idea.trim()) {
      form.value.idea = `${header}${parsed.content}`;
    } else {
      form.value.idea = `${form.value.idea.trim()}\n\n${header}${parsed.content}`;
    }
    ElMessage.success(`已提取「${parsed.filename}」内容（共 ${parsed.char_count} 字）至需求输入框`);
    if (form.value.idea.length > 20000) {
      ElMessage.warning(`当前内容共 ${form.value.idea.length} 字，超出 20000 字上限，请适当删减`);
    }
  } catch {
    // 错误已被响应拦截器处理
  } finally {
    parsingFile.value = false;
  }
  return false;
}

function handlePaste(event: ClipboardEvent) {
  const files = event.clipboardData?.files;
  if (files && files.length > 0) {
    const file = files[0];
    const name = file.name.toLowerCase();
    if (COMMON_FILE_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      event.preventDefault();
      handleFileUpload(file);
    }
  }
}

function handleDrop(event: DragEvent) {
  const files = event.dataTransfer?.files;
  if (files && files.length > 0) {
    const file = files[0];
    const name = file.name.toLowerCase();
    if (COMMON_FILE_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      event.preventDefault();
      handleFileUpload(file);
    }
  }
}

const dictStore = useDictStore();
dictStore.ensureLoaded();

/** 风格专属推荐基调映射表（结合各技能包权威定义，用于下拉高频置顶） */
const STYLE_TONES_MAP: Record<string, string[]> = {
  shangmeiying: ["仙气", "禅意", "史诗", "悲壮", "苍凉", "神性", "诡秘", "诙谐"],
  generic: ["史诗", "空灵", "治愈", "悬疑", "热血", "庄严", "幽默", "科幻"],
  handdrawn: ["温馨", "治愈", "童趣", "幽默", "怀旧", "轻松"],
};

/** 通用基调备选列表（字典离线时的兜底数据） */
const DEFAULT_TONES = [
  "史诗",
  "空灵",
  "治愈",
  "仙气",
  "禅意",
  "悬疑",
  "热血",
  "悲壮",
  "苍凉",
  "庄严",
  "温馨",
  "幽默",
  "神性",
  "诡秘",
  "科幻",
  "童趣",
  "怀旧",
];

/** 当前风格可用画幅（注册表预设；未选风格时为空） */
const aspectOptions = computed(
  () => props.styles.find((s) => s.key === form.value.style_key)?.aspect_ratios ?? []
);

interface ToneOptionItem {
  label: string;
  value: string;
  remark?: string | null;
}

/** 从字典 story_tone 获取基调，按当前选择的风格智能高频置顶 */
const toneOptions = computed<ToneOptionItem[]>(() => {
  const dictItems = dictStore.getOptions("story_tone");
  let items: ToneOptionItem[] = [];

  if (dictItems && dictItems.length > 0) {
    items = dictItems.map((d) => ({
      label: d.label,
      value: d.value,
      remark: d.remark,
    }));
  } else {
    items = DEFAULT_TONES.map((t) => ({ label: t, value: t }));
  }

  // 若当前已选定风格，将该风格推荐的基调优先排在前面
  const preferred = form.value.style_key ? STYLE_TONES_MAP[form.value.style_key] : null;
  if (preferred && preferred.length > 0) {
    const high = items.filter((item) => preferred.includes(item.value));
    const rest = items.filter((item) => !preferred.includes(item.value));
    items = [...high, ...rest];
  }

  // 若用户已填写了不在预设列表中的自定义基调，追加保留展示
  if (form.value.tone && !items.some((item) => item.value === form.value.tone)) {
    items = [{ label: form.value.tone, value: form.value.tone, remark: "自定义" }, ...items];
  }

  return items;
});

/** 切换风格时画幅回落到该风格首选（默认优先 16:9） */
function onStyleChange() {
  if (!aspectOptions.value.includes(form.value.aspect_ratio ?? "")) {
    form.value.aspect_ratio = aspectOptions.value.includes("16:9")
      ? "16:9"
      : aspectOptions.value[0] ?? null;
  }
}

/** 空白文本提示直接给出上传文件后缀，并根据模式自适应 */
const inputPlaceholder = computed(() => {
  const exts = COMMON_FILE_EXTENSIONS.join("、");
  if (isImageMode.value) {
    return `[生图模式] 输入画面提示词（人物立绘、分镜关键帧、场景氛围等），支持上传文件：${exts}`;
  }
  return `输入故事设定与创作需求，支持上传文件：${exts}`;
});

/** 画幅换算对应的生图规格尺寸 */
function mapRatioToSize(ratio?: string | null): string {
  if (!ratio) return "1536x1024";
  switch (ratio) {
    case "16:9":
    case "4:3":
    case "3:2":
      return "1536x1024";
    case "9:16":
    case "3:4":
    case "2:3":
      return "1024x1536";
    case "1:1":
      return "1024x1024";
    default:
      return "1536x1024";
  }
}

/** 提交生图请求（调用图像生成模型） */
function handleCreateImage() {
  const prompt = (form.value.idea ?? "").trim();
  if (!prompt) {
    ElMessage.warning("请在输入框中填写出图提示词");
    return;
  }
  const size = mapRatioToSize(form.value.aspect_ratio);
  emit("generateArt", {
    prompt,
    size,
  });
  form.value.idea = "";
}

/** 快捷键或统一回车提交 */
function handleSubmit() {
  if (isImageMode.value) {
    handleCreateImage();
  } else {
    if (!props.generating) {
      emit("send");
    }
  }
}
</script>

<template>
  <div class="gen-form-wrapper">
    <!-- 现代化圆角卡片容器 -->
    <div class="composer-card" :class="{ 'image-mode-active': isImageMode }">
      <!-- 顶部轻量参数胶囊条 -->
      <div class="form-row">
        <el-select
          v-model="form.style_key"
          placeholder="视频风格"
          size="small"
          class="modern-select style-select"
          @change="onStyleChange"
        >
          <el-option
            v-for="style in styles"
            :key="style.key"
            :value="style.key"
            :label="style.name"
          />
        </el-select>

        <el-select
          v-model="form.aspect_ratio"
          placeholder="画幅"
          size="small"
          class="modern-select aspect-select"
        >
          <el-option v-for="ratio in aspectOptions" :key="ratio" :value="ratio" :label="ratio" />
        </el-select>

        <template v-if="!isImageMode">
          <el-input-number
            v-model="form.episodes"
            :min="1"
            :max="50"
            size="small"
            controls-position="right"
            placeholder="集数"
            class="modern-input-number episodes-input"
          />

          <el-select
            v-model="form.tone"
            placeholder="基调"
            size="small"
            clearable
            filterable
            allow-create
            default-first-option
            class="modern-select tone-select"
          >
            <el-option
              v-for="t in toneOptions"
              :key="t.value"
              :value="t.value"
              :label="t.label"
            >
              <div class="tone-option-item">
                <span>{{ t.label }}</span>
                <span v-if="t.remark" class="tone-option-desc">{{ t.remark }}</span>
              </div>
            </el-option>
          </el-select>
        </template>

        <div v-else class="mode-tag-capsule">
          <span class="mode-tag-icon">✨</span>
          <span>生图模式 (立绘/关键帧)</span>
        </div>
      </div>

      <!-- 现代化边框无感文本输入区 -->
      <div
        class="input-row"
        @paste="handlePaste"
        @drop.prevent="handleDrop"
        @dragover.prevent
      >
        <el-input
          v-model="form.idea"
          type="textarea"
          :rows="3"
          :maxlength="20000"
          show-word-limit
          :disabled="generating || generatingArt"
          :placeholder="inputPlaceholder"
          class="modern-textarea"
          @keydown.enter.ctrl.prevent="handleSubmit"
          @keydown.enter.meta.prevent="handleSubmit"
        />
      </div>

      <!-- 底部工具与操作栏 -->
      <div class="action-row">
        <div class="action-left">
          <!-- 上传参考文档 -->
          <el-upload
            :show-file-list="false"
            :before-upload="handleFileUpload"
            :accept="COMMON_FILE_ACCEPT"
            :disabled="generating || generatingArt || parsingFile"
          >
            <button
              type="button"
              class="toolbar-pill-btn"
              :disabled="generating || generatingArt || parsingFile"
              title="上传参考文档提取内容"
            >
              <el-icon :class="{ 'is-loading': parsingFile }"><Paperclip /></el-icon>
              <span>{{ parsingFile ? "解析中..." : "上传文档" }}</span>
            </button>
          </el-upload>

          <!-- 单点按钮「创建图片」：点击后常亮，切换为调用图像生成模型 -->
          <button
            type="button"
            class="toolbar-pill-btn image-toggle-btn"
            :class="{ active: isImageMode }"
            :disabled="generating"
            title="点击切换生图模式（调用图像生成模型）"
            @click="toggleImageMode"
          >
            <el-icon><Picture /></el-icon>
            <span>创建图片</span>
            <span v-if="isImageMode" class="active-glow-dot"></span>
          </button>
        </div>

        <div class="action-right">
          <!-- 生图模式主操作 -->
          <template v-if="isImageMode">
            <el-button
              type="primary"
              size="small"
              class="modern-cta-btn image-cta-btn"
              :loading="generatingArt"
              :icon="Picture"
              @click="handleCreateImage"
            >
              生成图片
            </el-button>
          </template>

          <!-- 剧本模式主操作 -->
          <template v-else>
            <el-button
              v-if="!generating"
              type="primary"
              size="small"
              class="modern-cta-btn script-cta-btn"
              :disabled="generatingArt"
              :icon="Promotion"
              @click="emit('send')"
            >
              生成剧本
            </el-button>
            <el-button
              v-else
              type="warning"
              size="small"
              class="modern-cta-btn stop-cta-btn"
              @click="emit('stop')"
            >
              停止生成
            </el-button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gen-form-wrapper {
  padding: 10px 12px 12px;
  background: #f7f8fc;
  border-top: 1px solid #edf2f7;
}

/* 现代化圆角卡片容器 */
.composer-card {
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
  padding: 10px 12px;
  box-shadow: 0 3px 12px -2px rgba(15, 23, 42, 0.04), 0 1px 4px -1px rgba(15, 23, 42, 0.02);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.composer-card:hover {
  border-color: #cbd5e1;
}

.composer-card:focus-within {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12), 0 4px 16px -2px rgba(15, 23, 42, 0.06);
}

.composer-card.image-mode-active {
  border-color: #818cf8;
  background: linear-gradient(180deg, #ffffff 0%, #fafbff 100%);
}

.composer-card.image-mode-active:focus-within {
  border-color: #4f46e5;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.16), 0 4px 16px -2px rgba(79, 70, 229, 0.08);
}

/* 顶部轻量参数行 */
.form-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

:deep(.modern-select .el-select__wrapper),
:deep(.modern-input-number .el-input__wrapper) {
  border-radius: 8px !important;
  box-shadow: 0 0 0 1px #e2e8f0 inset !important;
  transition: all 0.15s ease;
  background: #f8fafc;
}

:deep(.modern-select .el-select__wrapper:hover),
:deep(.modern-input-number .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
  background: #ffffff;
}

:deep(.modern-select .el-select__wrapper.is-focused),
:deep(.modern-input-number .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1.5px #6366f1 inset !important;
  background: #ffffff;
}

.style-select {
  flex: 1;
  min-width: 96px;
}

.aspect-select {
  min-width: 80px;
  max-width: 96px;
}

.episodes-input {
  width: 92px;
}

.tone-select {
  flex: 1;
  min-width: 88px;
  max-width: 110px;
}

.mode-tag-capsule {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 20px;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  color: #4f46e5;
  font-size: 11px;
  font-weight: 500;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.tone-option-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.tone-option-desc {
  font-size: 11px;
  color: #8c939d;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 现代化无界输入框 */
.input-row {
  padding: 2px 0;
}

:deep(.modern-textarea .el-textarea__inner) {
  border: none !important;
  box-shadow: none !important;
  background: transparent !important;
  padding: 4px 2px !important;
  font-size: 13px;
  line-height: 1.6;
  color: #1e293b;
  resize: none;
}

:deep(.modern-textarea .el-textarea__inner::placeholder) {
  color: #94a3b8;
  font-size: 12px;
}

/* 底部操作与工具栏 */
.action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 4px;
}

.action-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.toolbar-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #64748b;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  line-height: 1.4;
}

.toolbar-pill-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #334155;
  border-color: #cbd5e1;
}

.toolbar-pill-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 单点常亮按钮核心样式 */
.image-toggle-btn {
  position: relative;
}

.image-toggle-btn.active {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  border-color: #4f46e5;
  color: #ffffff;
  box-shadow: 0 2px 10px rgba(99, 102, 241, 0.38);
}

.image-toggle-btn.active:hover {
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.48);
}

.active-glow-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 6px #34d399;
  animation: pulse-glow 2s infinite ease-in-out;
}

@keyframes pulse-glow {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.8);
  }
}

.action-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.modern-cta-btn {
  border-radius: 8px !important;
  font-weight: 500 !important;
  padding: 7px 16px !important;
  font-size: 12px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

.script-cta-btn {
  background: #526ae2 !important;
  border-color: #526ae2 !important;
  box-shadow: 0 2px 6px rgba(82, 106, 226, 0.25);
}

.script-cta-btn:hover {
  background: #4157cb !important;
  border-color: #4157cb !important;
  box-shadow: 0 4px 12px rgba(82, 106, 226, 0.38);
}

.image-cta-btn {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important;
  border-color: #4f46e5 !important;
  box-shadow: 0 2px 10px rgba(99, 102, 241, 0.35);
}

.image-cta-btn:hover {
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.48);
}

.stop-cta-btn {
  box-shadow: 0 2px 6px rgba(230, 162, 60, 0.25);
}
</style>
