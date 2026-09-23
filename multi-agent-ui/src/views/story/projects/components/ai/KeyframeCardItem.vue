<script setup lang="ts">
/**
 * 关键帧卡片：AI 生成关键帧的呈现、五段式描述展示、提示词复制与"存入关键帧"沉淀。
 */
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { storyAiApi, type StoryKeyframeCard, type StoryMessageVO } from "@/api/story";
import { readKeyframe } from "../../composables/useStoryAi";
import { copyToClipboard } from "@/utils/clipboard";

const props = defineProps<{
  message: StoryMessageVO;
  sessionId?: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const kf = computed<StoryKeyframeCard | null>(() => readKeyframe(props.message));

/** 已沉淀标记 */
const isSedimented = computed(() => {
  const params = props.message.params ?? {};
  return !!(params["sedimented_keyframe_id"] || params["is_sedimented"]);
});

/** 限制标签文本字数，超出截断并以悬浮提示展示完整内容 */
function truncateTagText(text: string | null | undefined, maxChars = 10): string {
  if (!text) return "";
  const trimmed = text.trim();
  return trimmed.length > maxChars ? `${trimmed.slice(0, maxChars)}…` : trimmed;
}

const saving = ref(false);
const generatingImage = ref(false);

async function copyPrompt() {
  const promptText = kf.value?.prompt || props.message.prompt || "";
  if (!promptText) return;
  const ok = await copyToClipboard(promptText);
  if (ok) {
    ElMessage.success("关键帧出图提示词已复制");
  } else {
    ElMessage.error("复制失败，请手动选择复制");
  }
}

async function handleGenerateKeyframeImage() {
  const sessionId = props.sessionId || props.message.session_id;
  if (!sessionId) {
    ElMessage.warning("缺少会话上下文，无法发起生图");
    return;
  }
  const promptText = kf.value?.prompt || props.message.prompt || "";
  if (!promptText) {
    ElMessage.warning("该关键帧缺少出图提示词");
    return;
  }
  generatingImage.value = true;
  try {
    const kfName = kf.value?.name
      ? `关键帧：${kf.value.name}`
      : `关键帧 ${kf.value?.scene_no ?? "?"}-${kf.value?.shot_no ?? "?"}`;
    const refImages = props.message.params?.reference_images;
    await storyAiApi.generateArtDirect(sessionId, {
      prompt: promptText,
      name: kfName,
      size: "1536x1024",
      reference_images: Array.isArray(refImages) ? refImages : undefined,
    });
    ElMessage.success("已发起关键帧出图任务");
    emit("changed");
  } catch {
    // 错误拦截器统一处理
  } finally {
    generatingImage.value = false;
  }
}

async function handleSaveKeyframe() {
  if (saving.value) return;
  saving.value = true;
  try {
    const res = await storyAiApi.saveKeyframe(props.message.id);
    if (!props.message.params) {
      props.message.params = {};
    }
    const savedKf = res.data as Record<string, unknown> | undefined;
    props.message.params.sedimented_keyframe_id = String(savedKf?.id ?? "1");
    props.message.params.is_sedimented = true;
    ElMessage.success(
      `已存入项目关键帧库（镜头 ${kf.value?.scene_no ?? ""}-${kf.value?.shot_no ?? ""}）`
    );
    emit("changed");
  } catch {
    // 错误由请求拦截器统一提示
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="keyframe-card-item">
    <div class="card-head">
      <div class="head-left">
        <span class="card-badge">
          🎬 关键帧 {{ kf?.scene_no ?? "?" }}-{{ kf?.shot_no ?? "?" }}
        </span>
        <span class="card-name" :title="kf?.name || '未命名镜头'">{{ kf?.name || "未命名镜头" }}</span>
      </div>
      <div class="head-right">
        <el-tag v-if="isSedimented" size="small" type="success">已入库</el-tag>
        <el-button
          v-else
          size="small"
          type="primary"
          link
          :loading="saving"
          @click="handleSaveKeyframe"
        >
          存入关键帧
        </el-button>
      </div>
    </div>

    <!-- 标签特征：限制显示字数，鼠标悬停展示完整内容 -->
    <div
      v-if="kf?.camera_description || kf?.lighting_description || kf?.style_description"
      class="card-tags"
    >
      <el-tooltip
        v-if="kf?.camera_description"
        :content="`镜头：${kf.camera_description}`"
        placement="top"
        :show-after="200"
      >
        <el-tag size="small" effect="plain" type="info" class="meta-tag">
          📷 {{ truncateTagText(kf.camera_description, 10) }}
        </el-tag>
      </el-tooltip>
      <el-tooltip
        v-if="kf?.lighting_description"
        :content="`光影：${kf.lighting_description}`"
        placement="top"
        :show-after="200"
      >
        <el-tag size="small" effect="plain" type="warning" class="meta-tag">
          💡 {{ truncateTagText(kf.lighting_description, 10) }}
        </el-tag>
      </el-tooltip>
      <el-tooltip
        v-if="kf?.style_description"
        :content="`风格：${kf.style_description}`"
        placement="top"
        :show-after="200"
      >
        <el-tag size="small" effect="plain" type="success" class="meta-tag">
          🎨 {{ truncateTagText(kf.style_description, 10) }}
        </el-tag>
      </el-tooltip>
    </div>

    <!-- 核心视觉描述 -->
    <div v-if="kf?.visual_description" class="desc-row">
      <span class="desc-label">画面：</span>
      <span class="desc-text">{{ kf.visual_description }}</span>
    </div>

    <!-- 剧情与完整描述 -->
    <div v-if="kf?.scene_description" class="desc-row">
      <span class="desc-label">剧情：</span>
      <span class="desc-text">{{ kf.scene_description }}</span>
    </div>
    <div v-if="kf?.camera_description" class="desc-row">
      <span class="desc-label">镜头：</span>
      <span class="desc-text">{{ kf.camera_description }}</span>
    </div>
    <div v-if="kf?.lighting_description" class="desc-row">
      <span class="desc-label">光影：</span>
      <span class="desc-text">{{ kf.lighting_description }}</span>
    </div>
    <div v-if="kf?.style_description" class="desc-row">
      <span class="desc-label">风格：</span>
      <span class="desc-text">{{ kf.style_description }}</span>
    </div>

    <!-- 提示词区域 -->
    <div v-if="kf?.prompt" class="prompt-box">
      <div class="prompt-head">
        <span class="prompt-title">🎨 出图提示词</span>
        <div class="prompt-head-actions">
          <el-button size="small" link type="primary" @click="copyPrompt">复制提示词</el-button>
          <el-button
            size="small"
            link
            type="primary"
            :loading="generatingImage"
            @click="handleGenerateKeyframeImage"
          >
            生成图片
          </el-button>
        </div>
      </div>
      <div class="prompt-content">
        {{ kf.prompt }}
      </div>
    </div>

    <!-- 底部操作 -->
    <div v-if="!isSedimented" class="card-actions">
      <el-button size="small" type="primary" :loading="saving" @click="handleSaveKeyframe">
        存入关键帧
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.keyframe-card-item {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  padding: 10px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: all 0.2s;
  flex-shrink: 0;
}

.keyframe-card-item:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  gap: 8px;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.card-badge {
  font-size: 12px;
  font-weight: 600;
  color: #3b82f6;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
  white-space: nowrap;
}

.card-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.head-right {
  flex-shrink: 0;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.meta-tag {
  cursor: pointer;
  flex-shrink: 0;
}

.desc-row {
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
  margin-bottom: 6px;
}

.desc-label {
  font-weight: 600;
  color: #64748b;
}

.desc-text {
  color: #334155;
}

.prompt-box {
  background: #f8fafc;
  border: 1px solid #edf2f7;
  border-radius: 6px;
  padding: 6px 8px;
  margin-top: 6px;
  margin-bottom: 8px;
}

.prompt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.prompt-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prompt-title {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
}

.prompt-content {
  font-size: 11px;
  line-height: 1.5;
  color: #475569;
  word-break: break-all;
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  border-top: 1px dashed #f1f5f9;
  padding-top: 6px;
  margin-top: 4px;
}
</style>
