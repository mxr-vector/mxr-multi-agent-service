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

const saving = ref(false);
const expanded = ref(false);

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
        <span class="card-name">{{ kf?.name || "未命名镜头" }}</span>
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

    <!-- 标签特征 -->
    <div class="card-tags">
      <el-tag v-if="kf?.camera_description" size="small" effect="plain" type="info">
        📷 {{ kf.camera_description }}
      </el-tag>
      <el-tag v-if="kf?.lighting_description" size="small" effect="plain" type="warning">
        💡 {{ kf.lighting_description }}
      </el-tag>
    </div>

    <!-- 核心视觉描述 -->
    <div v-if="kf?.visual_description" class="desc-row">
      <span class="desc-label">画面：</span>
      <span class="desc-text">{{ kf.visual_description }}</span>
    </div>

    <!-- 剧情描述 -->
    <div v-if="kf?.scene_description && expanded" class="desc-row">
      <span class="desc-label">剧情：</span>
      <span class="desc-text">{{ kf.scene_description }}</span>
    </div>

    <!-- 提示词区域 -->
    <div v-if="kf?.prompt" class="prompt-box">
      <div class="prompt-head">
        <span class="prompt-title">🎨 出图提示词</span>
        <el-button size="small" link type="primary" @click="copyPrompt">复制提示词</el-button>
      </div>
      <div class="prompt-content" :class="{ clamp: !expanded }">
        {{ kf.prompt }}
      </div>
    </div>

    <!-- 底部操作与折叠 -->
    <div class="card-actions">
      <el-button size="small" link type="info" @click="expanded = !expanded">
        {{ expanded ? "收起详情" : "展开详情" }}
      </el-button>
      <el-button v-if="!isSedimented" size="small" type="primary" :loading="saving" @click="handleSaveKeyframe">
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
}

.head-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-badge {
  font-size: 12px;
  font-weight: 600;
  color: #3b82f6;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
}

.card-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
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

.prompt-content.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px dashed #f1f5f9;
  padding-top: 6px;
  margin-top: 4px;
}
</style>
