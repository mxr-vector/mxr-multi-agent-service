<script setup lang="ts">
/**
 * 人物立绘生成卡片：展示立绘生图状态（生成中/成功/失败）、图片预览、提示词与存入角色库。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { CopyDocument, Picture, Refresh } from "@element-plus/icons-vue";
import {
  storyAiApi,
  storyFileUrl,
  type StoryMessageVO,
} from "@/api/story";
import { copyToClipboard } from "@/utils/clipboard";

const props = defineProps<{
  message: StoryMessageVO;
  sessionId?: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const params = computed(() => (props.message.params ?? {}) as Record<string, unknown>);

/** 提取图片名称（优先 params.card_name，次选 content 去前缀） */
const cardName = computed(() => {
  if (params.value.card_name && typeof params.value.card_name === "string") {
    return params.value.card_name;
  }
  const raw = props.message.content || "";
  return (
    raw
      .replace(/^(立绘|生成人物立绘|生成图像|图像|关键帧|图片|创建图片)[：:]\s*/, "")
      .trim() || ""
  );
});

/** 图像卡片标题展示（兼顾立绘、关键帧与普通出图） */
const cardTitle = computed(() => {
  const name = cardName.value;
  if (!name) return "图片生成";
  if (
    name.startsWith("立绘") ||
    name.startsWith("关键帧") ||
    name.startsWith("图片") ||
    name.startsWith("镜头")
  ) {
    return name;
  }
  return `图片：${name}`;
});

/** 是否已存入角色库 */
const isSedimented = computed(() => {
  return !!params.value.sedimented_character_id;
});

/** 规格尺寸摘要（如 1536x1024） */
const sizeSummary = computed(() => {
  const size = params.value.size;
  return typeof size === "string" && size ? size : "";
});

/** 提示词显示 */
const promptText = computed(() => {
  return props.message.prompt || "";
});

/** 参考图列表读取 */
const referenceImages = computed<string[]>(() => {
  const refs = params.value.reference_images;
  if (Array.isArray(refs)) {
    return refs.filter((r) => typeof r === "string" && r);
  }
  return [];
});

// —— 轮询生成中任务 ——
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let disposed = false;
const polling = ref(false);
const POLL_INTERVAL_MS = 2500;
const POLL_MAX_ATTEMPTS = 50;
let pollAttempts = 0;

function startPolling(taskId: string) {
  if (disposed || polling.value) return;
  polling.value = true;
  pollAttempts = 0;

  async function step() {
    if (disposed) return;
    if (pollAttempts++ >= POLL_MAX_ATTEMPTS) {
      polling.value = false;
      ElMessage.warning("立绘生成查询超时，请稍后刷新查看");
      return;
    }
    try {
      const res = await storyAiApi.task(taskId);
      if (disposed) return;
      const task = res.data;
      if (task.status === "succeeded") {
        polling.value = false;
        props.message.status = "done";
        if (task.result_image_file) {
          props.message.image_file = task.result_image_file;
        }
        ElMessage.success(`「${cardTitle.value}」生成完成`);
        emit("changed");
        return;
      }
      if (task.status === "failed" || task.status === "cancelled") {
        polling.value = false;
        props.message.status = task.status === "cancelled" ? "stopped" : "failed";
        props.message.error = task.error_message || "生成未完成";
        emit("changed");
        return;
      }
      pollTimer = setTimeout(step, POLL_INTERVAL_MS);
    } catch {
      pollTimer = setTimeout(step, POLL_INTERVAL_MS);
    }
  }

  step();
}

function checkPollNeeded() {
  if (props.message.status === "generating") {
    const taskId = String(params.value.generation_task_id || "");
    if (taskId) {
      startPolling(taskId);
    }
  }
}

onMounted(() => {
  checkPollNeeded();
});

watch(
  () => props.message.status,
  (status) => {
    if (status === "generating") {
      checkPollNeeded();
    }
  }
);

onBeforeUnmount(() => {
  disposed = true;
  if (pollTimer) clearTimeout(pollTimer);
});

// —— 存入角色库 ——
const savingArt = ref(false);

async function handleSaveArt() {
  if (savingArt.value) return;
  savingArt.value = true;
  try {
    const res = await storyAiApi.saveArt(props.message.id);
    if (!props.message.params) {
      props.message.params = {};
    }
    const char = res.data?.character as Record<string, unknown> | undefined;
    props.message.params.sedimented_character_id = String(char?.id ?? "1");
    ElMessage.success(
      `立绘已成功存入角色库${char?.name ? `（角色「${String(char.name)}」）` : ""}`
    );
    emit("changed");
  } catch {
    // 错误拦截器统一提示
  } finally {
    savingArt.value = false;
  }
}

// —— 复制提示词 ——
async function handleCopyPrompt() {
  if (!promptText.value) return;
  const ok = await copyToClipboard(promptText.value);
  if (ok) {
    ElMessage.success("出图提示词已复制到剪贴板");
  } else {
    ElMessage.error("复制失败，请手动选择复制");
  }
}

// —— 重新生成 ——
const retrying = ref(false);

async function handleRetry() {
  const sessionId = props.message.session_id || props.sessionId;
  if (!sessionId) {
    ElMessage.warning("缺少会话上下文，无法重新生成");
    return;
  }
  if (!promptText.value) {
    ElMessage.warning("该立绘缺少出图提示词");
    return;
  }
  retrying.value = true;
  try {
    const cardMsgId = params.value.card_message_id as string | undefined;
    const res = await storyAiApi.generateArtDirect(sessionId, {
      prompt: promptText.value,
      name: cardName.value,
      card_message_id: cardMsgId,
      size: (params.value.size as string) || undefined,
      quality: (params.value.quality as string) || undefined,
      reference_images: referenceImages.value.length ? referenceImages.value : undefined,
    });
    ElMessage.success("已发起重新生成图片任务");
    emit("changed");
    if (res.data?.id) {
      startPolling(res.data.id);
    }
  } catch {
    // 错误拦截器统一处理
  } finally {
    retrying.value = false;
  }
}
</script>

<template>
  <div class="art-card-item">
    <!-- 卡片头部 -->
    <div class="card-head">
      <div class="head-left">
        <el-icon class="head-icon"><Picture /></el-icon>
        <span class="card-title">{{ cardTitle }}</span>
        <el-tag v-if="sizeSummary" size="small" type="info" effect="plain" class="meta-tag">
          {{ sizeSummary }}
        </el-tag>
      </div>
      <div class="head-right">
        <el-tag v-if="message.status === 'generating'" size="small" type="warning" class="status-tag">
          <span class="dot-flashing"></span>
          生成中
        </el-tag>
        <el-tag v-else-if="isSedimented" size="small" type="success" class="status-tag">
          已入库
        </el-tag>
        <el-tag v-else-if="message.status === 'failed'" size="small" type="danger" class="status-tag">
          生成失败
        </el-tag>
      </div>
    </div>

    <!-- 卡片主体：图片展示 / 生成中骨架 / 失败提示 -->
    <div class="card-body">
      <!-- 1. 生成成功且有图片 -->
      <template v-if="message.status === 'done' && message.image_file">
        <div class="image-wrapper">
          <el-image
            :src="storyFileUrl(message.image_file)"
            :preview-src-list="[storyFileUrl(message.image_file)]"
            fit="contain"
            class="art-image"
            preview-teleported
            loading="lazy"
          >
            <template #placeholder>
              <div class="image-loading-placeholder">
                <el-icon class="is-loading"><Refresh /></el-icon>
                <span>图片加载中...</span>
              </div>
            </template>
          </el-image>
        </div>
      </template>

      <!-- 2. 生成中态 -->
      <div v-else-if="message.status === 'generating'" class="generating-box">
        <div class="generating-spinner">
          <el-icon class="is-loading" :size="24"><Refresh /></el-icon>
        </div>
        <div class="generating-text">正在通过图像模型绘制图片，请稍候…</div>
        <div v-if="promptText" class="generating-prompt-preview">
          提示词：{{ promptText.slice(0, 100) }}{{ promptText.length > 100 ? '…' : '' }}
        </div>
      </div>

      <!-- 3. 失败态 -->
      <div v-else-if="message.status === 'failed'" class="failed-box">
        <el-alert
          type="error"
          :title="`${cardTitle}失败`"
          :description="message.error ?? '模型生成异常，请检查提示词或服务配置后重试'"
          :closable="false"
          show-icon
        />
      </div>

      <!-- 4. 参考图展示区域 -->
      <div v-if="referenceImages.length > 0" class="ref-images-box">
        <div class="ref-images-label">参考图（用于引导模型出图）：</div>
        <div class="ref-images-list">
          <el-image
            v-for="(refImg, idx) in referenceImages"
            :key="idx"
            :src="storyFileUrl(refImg)"
            :preview-src-list="referenceImages.map(storyFileUrl)"
            fit="cover"
            class="ref-thumbnail-img"
            preview-teleported
          />
        </div>
      </div>

      <!-- 5. 提示词区域 -->
      <div v-if="promptText" class="prompt-box">
        <div class="prompt-label">出图提示词：</div>
        <div class="prompt-content">{{ promptText }}</div>
      </div>
    </div>

    <!-- 卡片底部操作栏 -->
    <div class="card-actions">
      <div class="actions-left">
        <el-button
          v-if="promptText"
          size="small"
          link
          :icon="CopyDocument"
          @click="handleCopyPrompt"
        >
          复制提示词
        </el-button>
        <el-button
          v-if="message.status === 'done' && !isSedimented"
          size="small"
          type="primary"
          link
          :loading="savingArt"
          @click="handleSaveArt"
        >
          存入角色库
        </el-button>
      </div>
      <div class="actions-right">
        <el-button
          v-if="message.status === 'failed' || message.status === 'done'"
          size="small"
          link
          :icon="Refresh"
          :loading="retrying"
          @click="handleRetry"
        >
          重新生成
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.art-card-item {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.art-card-item:hover {
  border-color: #526ae2;
  box-shadow: 0 3px 12px rgba(82, 106, 226, 0.08);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.head-icon {
  color: #526ae2;
  font-size: 15px;
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2d3d;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta-tag {
  font-size: 11px;
}
.head-right {
  flex-shrink: 0;
}
.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.dot-flashing {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #e6a23c;
  animation: pulse 1.2s infinite ease-in-out;
}
@keyframes pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}
.card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.image-wrapper {
  background: #f8fafc;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 180px;
  max-height: 320px;
}
.art-image {
  width: 100%;
  max-height: 320px;
  display: block;
}
.image-loading-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: #9aa4b2;
  font-size: 12px;
  padding: 40px 0;
}
.generating-box {
  background: #fbfcfe;
  border: 1px dashed #c3cdea;
  border-radius: 8px;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
}
.generating-spinner {
  color: #526ae2;
}
.generating-text {
  font-size: 12px;
  color: #526ae2;
  font-weight: 500;
}
.generating-prompt-preview {
  font-size: 11px;
  color: #8c939d;
  max-width: 90%;
  word-break: break-all;
  line-height: 1.4;
}
.failed-box {
  border-radius: 8px;
  overflow: hidden;
}
.ref-images-box {
  background: #f8fafc;
  border-radius: 6px;
  padding: 6px 10px;
}
.ref-images-label {
  font-size: 11px;
  color: #9aa4b2;
  font-weight: 500;
  margin-bottom: 4px;
}
.ref-images-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ref-thumbnail-img {
  width: 48px;
  height: 48px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  cursor: pointer;
}
.prompt-box {
  background: #f8fafc;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  line-height: 1.5;
  color: #4b5563;
}
.prompt-label {
  color: #9aa4b2;
  font-weight: 500;
  margin-bottom: 2px;
}
.prompt-content {
  word-break: break-all;
  white-space: pre-wrap;
  max-height: 80px;
  overflow-y: auto;
}
.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid #f0f2f5;
  padding-top: 8px;
}
.actions-left,
.actions-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
