<script setup lang="ts">
/**
 * AI 绘图工作台：左对话面板（文本/图片输入 + SSE 流式回复 + 会话历史），
 * 右画布区（Mermaid 预览 / xmlpng 预览 + 版本链 + drawio 编辑入口）。
 *
 * 数据模型：每次 AI 生成或用户编辑保存都是版本链上的一条新记录（append-only），
 * 画布始终展示 currentVersion；多轮改图以 currentVersion 为基线（base_version_id）。
 */
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  DrawChatApi,
  DrawSessionApi,
  DrawVersionApi,
  type DrawMessageVO,
  type DrawSessionVO,
  type DrawStreamEvent,
  type DrawVersionVO,
} from "@/api/draw";
import MermaidPreview from "./components/MermaidPreview.vue";
import DrawioEditorDialog from "./components/DrawioEditorDialog.vue";

/** 上传/预览文件的公开访问基址（静态挂载 {BASE_URL}/public/files，免 token） */
const FILE_BASE = `${import.meta.env.VITE_APP_BASE_API}/public/files`;

// ---------- 会话与消息 ----------
const sessions = ref<DrawSessionVO[]>([]);
const currentSessionId = ref<string | null>(null);
const messages = ref<DrawMessageVO[]>([]);

// ---------- 版本链 ----------
const versions = ref<DrawVersionVO[]>([]);
const currentVersion = ref<DrawVersionVO | null>(null);

// ---------- 输入与流式状态 ----------
const inputText = ref("");
const pendingImage = ref<File | null>(null);
const pendingImagePreview = ref("");
const isLoading = ref(false);
const thinkText = ref("");
const streamAnswer = ref("");
let abortStream: (() => void) | null = null;

// ---------- 编辑弹窗 ----------
const editorVisible = ref(false);
const editorVersion = ref<DrawVersionVO | null>(null);
const editorSaving = ref(false);

/** 流式期间从累积回复中截取 Mermaid 中间态（未闭合也返回，供节流预览） */
const streamingMermaid = computed(() => {
  const text = streamAnswer.value;
  const start = text.indexOf("```mermaid");
  if (start < 0) return "";
  const body = text.slice(start + "```mermaid".length);
  const end = body.indexOf("```");
  return (end >= 0 ? body.slice(0, end) : body).replace(/^\s*\n/, "");
});

/** 画布展示态：流式中显示中间态 Mermaid，否则显示当前版本 */
const canvasMermaid = computed(() =>
  isLoading.value ? streamingMermaid.value : (currentVersion.value?.mermaid_source ?? "")
);

/** 用户编辑版本的 xmlpng 预览地址 */
const previewUrl = computed(() =>
  currentVersion.value?.preview_file ? `${FILE_BASE}/${currentVersion.value.preview_file}` : ""
);

/** 当前版本是否以图片预览展示（用户编辑版本优先展示保存时的 xmlpng） */
const showImagePreview = computed(
  () => !isLoading.value && currentVersion.value?.source_type === "user" && !!previewUrl.value
);

// ============================================================
// 会话历史（5.3）
// ============================================================

async function loadSessions() {
  const res = await DrawSessionApi.list(1, 50);
  sessions.value = res.data?.items ?? [];
}

async function switchSession(sessionId: string) {
  if (isLoading.value) {
    ElMessage.warning("生成中，请先停止再切换会话");
    return;
  }
  currentSessionId.value = sessionId;
  const [msgRes, verRes] = await Promise.all([
    DrawSessionApi.messages(sessionId, 1, 200),
    DrawSessionApi.versions(sessionId),
  ]);
  messages.value = msgRes.data?.items ?? [];
  versions.value = verRes.data ?? [];
  currentVersion.value = versions.value.at(-1) ?? null;
  streamAnswer.value = "";
  thinkText.value = "";
}

function newSession() {
  if (isLoading.value) {
    ElMessage.warning("生成中，请先停止再新建会话");
    return;
  }
  currentSessionId.value = null;
  messages.value = [];
  versions.value = [];
  currentVersion.value = null;
  streamAnswer.value = "";
  thinkText.value = "";
}

async function removeSession(session: DrawSessionVO) {
  await ElMessageBox.confirm(
    `确定删除会话「${session.title}」？将同时删除其消息与图表版本。`,
    "删除会话",
    {
      type: "warning",
    }
  );
  await DrawSessionApi.remove(session.id);
  ElMessage.success("已删除");
  if (currentSessionId.value === session.id) newSession();
  await loadSessions();
}

// ============================================================
// 输入与流式生成（5.1）
// ============================================================

// 图片类型白名单（与后端 /draw/upload 的 IMAGE_EXTENSION_MIME 对齐）
const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp"];
const IMAGE_MIME_EXT: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
};

/** 校验并设置待重绘图片（选文件/粘贴两条路径共用） */
function setPendingImage(file: File) {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!IMAGE_EXTENSIONS.includes(ext)) {
    ElMessage.error("仅支持 png / jpg / jpeg / webp 图片");
    return;
  }
  if (file.size > 50 * 1024 * 1024) {
    ElMessage.error("图片超过大小上限（50MB）");
    return;
  }
  if (pendingImagePreview.value) URL.revokeObjectURL(pendingImagePreview.value);
  pendingImage.value = file;
  pendingImagePreview.value = URL.createObjectURL(file);
}

function onPickImage(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  (event.target as HTMLInputElement).value = "";
  if (file) setPendingImage(file);
}

/** 输入框 Ctrl+V 粘贴：剪贴板含图片时直接作为待重绘图片（截图无扩展名，按 MIME 补齐） */
function onPaste(event: ClipboardEvent) {
  const items = event.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.kind !== "file" || !(item.type in IMAGE_MIME_EXT)) continue;
    const file = item.getAsFile();
    if (!file) continue;
    event.preventDefault();
    const hasExt = file.name.includes(".");
    setPendingImage(
      hasExt
        ? file
        : new File([file], `粘贴图片-${Date.now()}.${IMAGE_MIME_EXT[item.type]}`, {
            type: item.type,
          })
    );
    return;
  }
}

function clearPendingImage() {
  if (pendingImagePreview.value) URL.revokeObjectURL(pendingImagePreview.value);
  pendingImage.value = null;
  pendingImagePreview.value = "";
}

function appendLocalMessage(partial: Partial<DrawMessageVO>) {
  messages.value.push({
    id: `local-${Date.now()}-${messages.value.length}`,
    session_id: currentSessionId.value ?? "",
    role: "user",
    content: "",
    image_file: null,
    sequence: messages.value.length + 1,
    status: "done",
    error: null,
    created_at: "",
    ...partial,
  } as DrawMessageVO);
}

async function send() {
  const question = inputText.value.trim();
  if (!question && !pendingImage.value) {
    ElMessage.warning("请输入描述或选择图片");
    return;
  }
  if (isLoading.value) return;
  isLoading.value = true;
  thinkText.value = "";
  streamAnswer.value = "";

  try {
    // 图片先经上传端点换取 image_file 相对路径
    let imageFile: string | undefined;
    if (pendingImage.value) {
      const res = await DrawChatApi.upload(pendingImage.value);
      imageFile = res.data?.image_file;
    }

    appendLocalMessage({ role: "user", content: question, image_file: imageFile ?? null });
    appendLocalMessage({ role: "assistant", content: "", status: "generating" });
    inputText.value = "";
    clearPendingImage();

    abortStream = await DrawChatApi.chatStream(
      {
        question,
        session_id: currentSessionId.value ?? undefined,
        image_file: imageFile,
        // 多轮改图基线：画布当前版本（AI 首图场景为空）
        base_version_id: currentVersion.value?.id ?? undefined,
      },
      onStreamEvent,
      (error) => {
        isLoading.value = false;
        ElMessage.error(error.message);
      },
      () => {
        isLoading.value = false;
      }
    );
  } catch (err: any) {
    isLoading.value = false;
    ElMessage.error(err?.message ?? "发送失败");
  }
}

function onStreamEvent(event: DrawStreamEvent) {
  const assistant = messages.value.at(-1);
  switch (event.event) {
    case "think":
      thinkText.value = event.text ?? "";
      if (event.session_id && !currentSessionId.value) {
        currentSessionId.value = event.session_id;
      }
      break;
    case "answer":
      streamAnswer.value += event.delta ?? "";
      if (assistant?.role === "assistant") assistant.content = streamAnswer.value;
      break;
    case "done": {
      isLoading.value = false;
      thinkText.value = "";
      if (assistant?.role === "assistant") assistant.status = event.done?.status ?? "done";
      void afterDone(event.done?.version_id ?? null);
      break;
    }
    case "error":
      isLoading.value = false;
      thinkText.value = "";
      if (assistant?.role === "assistant") assistant.status = "failed";
      ElMessage.error(event.msg ?? "生成失败");
      break;
  }
}

/** done 后收尾：刷新版本链与会话列表，把画布切到新版本 */
async function afterDone(versionId: string | null) {
  const sessionId = currentSessionId.value;
  if (!sessionId) return;
  const verRes = await DrawSessionApi.versions(sessionId);
  versions.value = verRes.data ?? [];
  if (versionId) {
    currentVersion.value =
      versions.value.find((v) => v.id === versionId) ?? versions.value.at(-1) ?? null;
  } else if (streamAnswer.value) {
    // 未产出合法 Mermaid：保留文本回复，画布不切换
    ElMessage.warning("本次回复未生成有效图表，可调整描述后重试");
  }
  void loadSessions();
}

async function stop() {
  if (currentSessionId.value) {
    await DrawChatApi.stop(currentSessionId.value);
  }
  abortStream?.();
  isLoading.value = false;
}

/** 渲染失败兜底的"重新生成"：以最后一条 user 消息内容重发 */
function regenerate() {
  const lastUser = [...messages.value].reverse().find((m) => m.role === "user");
  if (!lastUser) return;
  inputText.value = lastUser.content;
  void send();
}

// ============================================================
// 版本链与编辑（6.4 / 6.2 / 6.3）
// ============================================================

function selectVersion(version: DrawVersionVO) {
  if (isLoading.value) return;
  currentVersion.value = version;
}

async function openEditor(version: DrawVersionVO | null) {
  if (!version) return;
  // 编辑需要完整 XML（用户版本）——统一走详情接口取全量字段
  const res = await DrawVersionApi.detail(version.id);
  editorVersion.value = res.data ?? version;
  editorVisible.value = true;
}

async function handleEditorSave(payload: {
  parent: DrawVersionVO;
  drawio_xml: string;
  preview: Blob | null;
}) {
  if (!currentSessionId.value) return;
  editorSaving.value = true;
  try {
    const res = await DrawVersionApi.save({
      session_id: currentSessionId.value,
      parent_id: payload.parent.id,
      drawio_xml: payload.drawio_xml,
      preview: payload.preview,
    });
    ElMessage.success("已保存为新版本");
    editorVisible.value = false;
    const verRes = await DrawSessionApi.versions(currentSessionId.value);
    versions.value = verRes.data ?? [];
    currentVersion.value =
      versions.value.find((v) => v.id === res.data?.id) ?? versions.value.at(-1) ?? null;
  } finally {
    editorSaving.value = false;
  }
}

onMounted(loadSessions);
</script>

<template>
  <section class="draw-page">
    <div class="draw-layout">
      <!-- 左栏：会话 + 对话 -->
      <aside class="chat-panel content-card">
        <div class="chat-header">
          <h2>AI 绘图</h2>
          <button class="primary-button" type="button" @click="newSession">＋ 新绘图</button>
        </div>

        <div v-if="sessions.length" class="session-list">
          <div
            v-for="session in sessions"
            :key="session.id"
            class="session-item"
            :class="{ active: session.id === currentSessionId }"
            @click="switchSession(session.id)"
          >
            <span class="session-title">{{ session.title }}</span>
            <el-icon class="session-remove" @click.stop="removeSession(session)">
              <Delete />
            </el-icon>
          </div>
        </div>

        <div class="message-list">
          <div v-if="!messages.length" class="chat-empty">
            <p>描述你想画的图，或上传一张图片让 AI 用图表重绘。</p>
            <p class="chat-empty-sub">例如："画一个订单处理流程图"</p>
          </div>
          <div v-for="message in messages" :key="message.id" class="message" :class="message.role">
            <img
              v-if="message.image_file"
              :src="`${FILE_BASE}/${message.image_file}`"
              class="message-image"
              alt="上传图片"
            />
            <div v-if="message.content" class="message-bubble">{{ message.content }}</div>
            <div
              v-else-if="message.role === 'assistant' && message.status === 'generating'"
              class="message-bubble"
            >
              {{ thinkText || "正在生成图表…" }}
            </div>
            <span v-if="message.status === 'failed'" class="message-status">生成失败</span>
            <span v-else-if="message.status === 'stopped'" class="message-status">已停止</span>
          </div>
        </div>

        <div class="composer">
          <div v-if="pendingImagePreview" class="composer-image">
            <img :src="pendingImagePreview" alt="待重绘图片" />
            <el-icon class="composer-image-remove" @click="clearPendingImage">
              <Close />
            </el-icon>
          </div>
          <textarea
            v-model="inputText"
            class="composer-input"
            rows="3"
            placeholder="描述想要的图表，或附加图片说明…（Enter 发送，Shift+Enter 换行，支持粘贴图片）"
            @keydown.enter.exact.prevent="send"
            @paste="onPaste"
          ></textarea>
          <div class="composer-actions">
            <label class="upload-button">
              <input type="file" accept=".png,.jpg,.jpeg,.webp" hidden @change="onPickImage" />
              上传图片
            </label>
            <div class="composer-buttons">
              <el-button v-if="isLoading" size="small" @click="stop">停止</el-button>
              <el-button type="primary" size="small" :loading="isLoading" @click="send">
                发送
              </el-button>
            </div>
          </div>
        </div>
      </aside>

      <!-- 右栏：画布 + 版本链 -->
      <div class="canvas-panel content-card">
        <div class="canvas-toolbar">
          <div>
            <h2>画布</h2>
            <span v-if="currentVersion" class="canvas-meta">
              {{ currentVersion.source_type === "ai" ? "AI 生成" : "手工编辑" }} ·
              {{ currentVersion.created_at }}
            </span>
          </div>
          <el-button
            type="primary"
            size="small"
            :disabled="!currentVersion || isLoading"
            @click="openEditor(currentVersion)"
          >
            在 drawio 中编辑
          </el-button>
        </div>

        <div class="canvas-body">
          <img v-if="showImagePreview" :src="previewUrl" class="canvas-image" alt="图表预览" />
          <MermaidPreview
            v-else-if="canvasMermaid"
            :source="canvasMermaid"
            :streaming="isLoading"
            :can-regenerate="!isLoading"
            @regenerate="regenerate"
          />
          <div v-else class="canvas-empty">
            <p>暂无图表</p>
            <p class="chat-empty-sub">左侧发起对话后，生成的图表会展示在这里</p>
          </div>
        </div>

        <div v-if="versions.length" class="version-bar">
          <span class="version-label">版本链（{{ versions.length }}）</span>
          <div class="version-list">
            <button
              v-for="(version, index) in versions"
              :key="version.id"
              type="button"
              class="version-chip"
              :class="{
                active: version.id === currentVersion?.id,
                user: version.source_type === 'user',
              }"
              :title="`${version.source_type === 'ai' ? 'AI 生成' : '手工编辑'} · ${version.created_at}`"
              @click="selectVersion(version)"
            >
              v{{ index + 1 }}{{ version.source_type === "user" ? " ✎" : "" }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <DrawioEditorDialog
      v-model:visible="editorVisible"
      :version="editorVersion"
      :saving="editorSaving"
      @save="handleEditorSave"
    />
  </section>
</template>

<style scoped>
.draw-page {
  color: #273249;
  display: flex;
  flex: 1;
  min-height: 0;
}

/* 双栏骨架：左对话面板定宽 + 右画布吃满剩余（对齐 KnowledgeBase 布局约定） */
.draw-layout {
  display: flex;
  flex: 1;
  gap: 20px;
  min-height: 0;
  width: 100%;
}

.chat-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  width: 380px;
  flex-shrink: 0;
}

.canvas-panel {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  min-width: 0;
}

.chat-header,
.canvas-toolbar {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.chat-header h2,
.canvas-toolbar h2 {
  font-size: 16px;
  margin: 0;
}

.canvas-meta {
  color: #8a94a6;
  font-size: 12px;
}

.session-list {
  display: flex;
  flex-shrink: 0;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.session-item {
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  cursor: pointer;
  display: flex;
  flex-shrink: 0;
  font-size: 12px;
  gap: 4px;
  max-width: 160px;
  padding: 4px 10px;
}

.session-item.active {
  background: #eef2ff;
  border-color: #6366f1;
  color: #4338ca;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-remove {
  color: #94a3b8;
  flex-shrink: 0;
}

.session-remove:hover {
  color: #dc2626;
}

.message-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.chat-empty,
.canvas-empty {
  color: #8a94a6;
  font-size: 13px;
  margin: auto;
  text-align: center;
}

.chat-empty-sub {
  font-size: 12px;
  margin-top: 4px;
}

.message {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message.user {
  align-items: flex-end;
}

.message.assistant {
  align-items: flex-start;
}

.message-bubble {
  background: #f1f5f9;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
  max-width: 92%;
  padding: 8px 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.message.user .message-bubble {
  background: #eef2ff;
}

.message-image {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  max-height: 120px;
  max-width: 200px;
  object-fit: contain;
}

.message-status {
  color: #dc2626;
  font-size: 12px;
}

.composer {
  border-top: 1px solid #eef1f6;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  gap: 8px;
  padding-top: 10px;
}

.composer-image {
  position: relative;
  width: fit-content;
}

.composer-image img {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  max-height: 80px;
}

.composer-image-remove {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 50%;
  cursor: pointer;
  padding: 2px;
  position: absolute;
  right: -8px;
  top: -8px;
}

.composer-input {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  padding: 8px 10px;
  resize: none;
}

.composer-input:focus {
  border-color: #6366f1;
  outline: none;
}

.composer-actions {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.upload-button {
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  color: #64748b;
  cursor: pointer;
  font-size: 12px;
  padding: 4px 10px;
}

.upload-button:hover {
  border-color: #6366f1;
  color: #4338ca;
}

.canvas-body {
  border: 1px solid #eef1f6;
  border-radius: 10px;
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.canvas-image {
  margin: auto;
  max-height: 100%;
  max-width: 100%;
  object-fit: contain;
}

.version-bar {
  align-items: center;
  display: flex;
  flex-shrink: 0;
  gap: 10px;
}

.version-label {
  color: #8a94a6;
  font-size: 12px;
  flex-shrink: 0;
}

.version-list {
  display: flex;
  gap: 6px;
  overflow-x: auto;
}

.version-chip {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  cursor: pointer;
  font-size: 12px;
  padding: 3px 10px;
}

.version-chip.user {
  border-style: dashed;
}

.version-chip.active {
  background: #eef2ff;
  border-color: #6366f1;
  color: #4338ca;
}

@media (max-width: 960px) {
  /* 窄屏回退：双栏改纵向堆叠 */
  .draw-layout {
    flex-direction: column;
  }

  .chat-panel {
    width: 100%;
  }
}
</style>
