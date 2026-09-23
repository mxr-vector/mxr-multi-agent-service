<script setup lang="ts">
/**
 * 人物立绘生成卡片：展示立绘生图状态（生成中/成功/失败）、图片预览、提示词与存入角色库。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { CopyDocument, Picture, Refresh } from "@element-plus/icons-vue";
import {
  keyframeApi,
  storyAiApi,
  storyFileUrl,
  type StoryKeyframeVO,
  type StoryMessageVO,
} from "@/api/story";
import { copyToClipboard } from "@/utils/clipboard";

const props = defineProps<{
  message: StoryMessageVO;
  sessionId?: string;
  projectId?: string;
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

/** 是否属于关键帧相关出图 */
const isKeyframe = computed(() => {
  const cardType = String(params.value.card_type || "");
  if (cardType === "keyframe") return true;
  const name = cardName.value || props.message.content || "";
  return (
    name.startsWith("关键帧") ||
    name.startsWith("镜头") ||
    name.includes("关键帧") ||
    name.includes("分镜")
  );
});

/** 是否已存入正式资产库（关键帧看 sedimented_keyframe_id，角色立绘看 sedimented_character_id） */
const isSedimented = computed(() => {
  if (isKeyframe.value) {
    return !!(params.value.sedimented_keyframe_id || params.value.is_sedimented);
  }
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

// —— 存入角色库（角色立绘） ——
const savingArt = ref(false);

async function handleSaveCharacterArt() {
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

// —— 存入关键帧（弹窗选择目标关键帧或新建） ——
const kfDialogVisible = ref(false);
const loadingKeyframes = ref(false);
const submittingKf = ref(false);
const projectKeyframes = ref<StoryKeyframeVO[]>([]);
const saveMode = ref<"existing" | "new">("existing");
const selectedKeyframeId = ref<string>("");

// 新建模式字段
const newSceneNo = ref<number>(1);
const newShotNo = ref<number>(1);
const newKfName = ref<string>("");

/** 解析当前卡片或名称中的场景与镜头编号 */
function extractSceneShotFromName(name: string): { scene: number | null; shot: number | null } {
  const match = /(\d+)[-_](\d+)/.exec(name);
  if (match) {
    return { scene: Number(match[1]), shot: Number(match[2]) };
  }
  return { scene: null, shot: null };
}

/** 打开存入关键帧选择弹窗 */
async function openSaveKeyframeDialog() {
  kfDialogVisible.value = true;
  saveMode.value = "existing";
  selectedKeyframeId.value = "";
  newKfName.value = cardName.value || "新分镜镜头";
  newSceneNo.value = 1;
  newShotNo.value = 1;

  const rawName = cardName.value || props.message.content || "";
  const { scene, shot } = extractSceneShotFromName(rawName);

  if (props.projectId) {
    loadingKeyframes.value = true;
    try {
      const res = await keyframeApi.list(props.projectId, { size: 100 });
      const items = res.data?.items ?? [];
      projectKeyframes.value = items;

      // 计算下一个推荐的镜头编号
      const maxShot = items.reduce((max, k) => Math.max(max, k.shot_no ?? 0), 0);
      newShotNo.value = maxShot + 1;

      // 智能自动预选：
      // 1. 若名称中包含编号（如 1-1），自动寻找匹配项
      // 2. 否则若有卡片，尝试按名称模糊匹配
      if (scene !== null && shot !== null) {
        const match = items.find((k) => k.scene_no === scene && k.shot_no === shot);
        if (match) {
          selectedKeyframeId.value = match.id;
        }
      } else if (items.length > 0) {
        const cleanName = rawName.replace(/^关键帧[：:\s]*/, "").trim();
        const match = items.find((k) => k.name && cleanName.includes(k.name));
        if (match) {
          selectedKeyframeId.value = match.id;
        } else {
          selectedKeyframeId.value = items[0].id;
        }
      } else {
        // 项目内暂无任何关键帧，自动切为新建模式
        saveMode.value = "new";
      }
    } catch {
      // 请求拦截器统一提示
    } finally {
      loadingKeyframes.value = false;
    }
  }
}

/** 当前选中的目标关键帧 */
const currentSelectedKeyframe = computed(() => {
  return projectKeyframes.value.find((k) => k.id === selectedKeyframeId.value) ?? null;
});

/** 确认存入关键帧 */
async function confirmSaveKeyframe() {
  submittingKf.value = true;
  try {
    let payload: { target_keyframe_id?: string; scene_no?: number; shot_no?: number; name?: string } = {};
    if (saveMode.value === "existing") {
      if (!selectedKeyframeId.value) {
        ElMessage.warning("请选择要存入的目标关键帧");
        return;
      }
      payload = { target_keyframe_id: selectedKeyframeId.value };
    } else {
      if (!newSceneNo.value || !newShotNo.value) {
        ElMessage.warning("请输入场景号与镜头号");
        return;
      }
      payload = {
        scene_no: newSceneNo.value,
        shot_no: newShotNo.value,
        name: newKfName.value.trim() || undefined,
      };
    }

    const res = await storyAiApi.saveKeyframe(props.message.id, payload);
    if (!props.message.params) {
      props.message.params = {};
    }
    const kf = res.data as Record<string, unknown> | undefined;
    props.message.params.sedimented_keyframe_id = String(kf?.id ?? "1");
    props.message.params.is_sedimented = true;
    ElMessage.success(
      `图片已成功存入关键帧（镜头 ${kf?.scene_no ?? "?"}-${kf?.shot_no ?? "?"}）`
    );
    kfDialogVisible.value = false;
    emit("changed");
  } catch {
    // 请求拦截器统一提示
  } finally {
    submittingKf.value = false;
  }
}

function handleSaveClick() {
  if (isKeyframe.value) {
    openSaveKeyframeDialog();
  } else {
    handleSaveCharacterArt();
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
          @click="handleSaveClick"
        >
          {{ isKeyframe ? "存入关键帧" : "存入角色库" }}
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

    <!-- 存入关键帧选择弹窗 -->
    <el-dialog
      v-model="kfDialogVisible"
      title="存入项目关键帧"
      width="520px"
      append-to-body
      destroy-on-close
    >
      <div v-loading="loadingKeyframes" class="save-kf-dialog-content">
        <!-- 待存入画面预览与信息 -->
        <div class="save-kf-preview">
          <el-image
            v-if="message.image_file"
            :src="storyFileUrl(message.image_file)"
            fit="cover"
            class="save-kf-thumb"
          />
          <div class="save-kf-info">
            <div class="save-kf-name">{{ cardTitle }}</div>
            <div v-if="promptText" class="save-kf-prompt" :title="promptText">
              {{ promptText }}
            </div>
          </div>
        </div>

        <el-divider style="margin: 14px 0" />

        <!-- 存入方式选择 -->
        <el-form label-position="top">
          <el-form-item label="存入目标">
            <el-radio-group v-model="saveMode" size="default">
              <el-radio-button value="existing" :disabled="projectKeyframes.length === 0">
                更新已有关键帧
              </el-radio-button>
              <el-radio-button value="new">新建为关键帧</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <!-- 模式一：选择已有关键帧 -->
          <template v-if="saveMode === 'existing'">
            <el-form-item label="选择目标关键帧" required>
              <el-select
                v-model="selectedKeyframeId"
                placeholder="请选择要存入/覆盖的关键帧"
                filterable
                style="width: 100%"
              >
                <el-option
                  v-for="kf in projectKeyframes"
                  :key="kf.id"
                  :value="kf.id"
                  :label="`镜头 ${kf.scene_no}-${kf.shot_no}：${kf.name || '未命名'} ${kf.image_file ? '（已有画面）' : '（待出图）'}`"
                >
                  <div class="kf-option-item">
                    <span class="kf-option-badge">镜头 {{ kf.scene_no }}-{{ kf.shot_no }}</span>
                    <span class="kf-option-name">{{ kf.name || "未命名镜头" }}</span>
                    <el-tag v-if="kf.image_file" size="small" type="warning" effect="plain">已有画面</el-tag>
                    <el-tag v-else size="small" type="info" effect="plain">待出图</el-tag>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>

            <div v-if="currentSelectedKeyframe?.image_file" class="save-kf-warn-tip">
              ⚠️ 该关键帧当前已存在画面，存入后将替换其现有图片。
            </div>
          </template>

          <!-- 模式二：新建关键帧 -->
          <template v-else>
            <div style="display: flex; gap: 12px">
              <el-form-item label="场景号" required style="flex: 1">
                <el-input-number v-model="newSceneNo" :min="1" :max="999" style="width: 100%" />
              </el-form-item>
              <el-form-item label="镜头号" required style="flex: 1">
                <el-input-number v-model="newShotNo" :min="1" :max="999" style="width: 100%" />
              </el-form-item>
            </div>
            <el-form-item label="关键帧名称">
              <el-input v-model="newKfName" placeholder="例如：长廊对峙 / 主角近景" maxlength="100" />
            </el-form-item>
          </template>
        </el-form>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="kfDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="submittingKf" @click="confirmSaveKeyframe">
            确认存入
          </el-button>
        </div>
      </template>
    </el-dialog>
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
.save-kf-preview {
  display: flex;
  gap: 12px;
  align-items: center;
  background: #f8fafc;
  padding: 10px;
  border-radius: 8px;
}
.save-kf-thumb {
  width: 90px;
  height: 60px;
  border-radius: 6px;
  flex-shrink: 0;
}
.save-kf-info {
  flex: 1;
  min-width: 0;
}
.save-kf-name {
  font-weight: 600;
  font-size: 13px;
  color: #1e293b;
  margin-bottom: 4px;
}
.save-kf-prompt {
  font-size: 11px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.kf-option-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 8px;
}
.kf-option-badge {
  font-weight: 600;
  color: #526ae2;
  font-size: 12px;
}
.kf-option-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: #334155;
}
.save-kf-warn-tip {
  font-size: 12px;
  color: #e6a23c;
  margin-top: -6px;
  margin-bottom: 10px;
}
</style>
