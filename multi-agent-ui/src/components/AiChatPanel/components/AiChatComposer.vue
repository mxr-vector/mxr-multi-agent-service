<template>
  <Transition name="afc-fade">
    <div v-if="showQuick" class="afc-quick">
      <button
        v-for="question in quickQuestions"
        :key="question"
        class="afc-quick__btn"
        @click="onSend(question)"
      >
        {{ question }}
      </button>
    </div>
  </Transition>

  <div class="afc-toolbar">
    <div class="afc-filter-stack">
      <div class="afc-db-picker">
        <el-select
          :model-value="selectedDbIds"
          placeholder="选择知识库"
          size="small"
          clearable
          multiple
          filterable
          collapse-tags
          class="afc-db-select"
          :loading="knowledgeLoading"
          loading-text="知识库加载中..."
          :no-data-text="knowledgeNoDataText"
          @visible-change="handleKnowledgeVisibleChange"
          @update:model-value="emit('update:selectedDbIds', $event)"
        >
          <template #prefix>
            <el-icon :size="12">
              <DataBoard />
            </el-icon>
          </template>
          <el-option
            v-for="db in knowledgeList"
            :key="db.value"
            :label="db.label"
            :value="db.value"
          />
        </el-select>
        <div v-if="selectedKnowledgeTags.length" class="afc-db-tags">
          <el-tag
            v-for="db in selectedKnowledgeTags"
            :key="db.value"
            closable
            size="small"
            class="afc-db-tag"
            @close="emit('remove-selected-db', db.value)"
          >
            {{ db.label }}
          </el-tag>
        </div>
      </div>
    </div>
    <div class="afc-file-upload">
      <el-upload
        :show-file-list="false"
        :before-upload="handleFileUpload"
        :accept="COMMON_FILE_ACCEPT"
        :disabled="isLoading || parsingFile"
      >
        <el-button size="small" :loading="parsingFile" class="afc-upload-btn">
          <template #icon>
            <el-icon><Paperclip /></el-icon>
          </template>
          {{ parsingFile ? "解析中..." : "上传文档" }}
        </el-button>
      </el-upload>
    </div>
  </div>

  <Transition name="afc-fade">
    <div v-if="quotedMessage" class="afc-quote-preview">
      <div class="afc-quote-preview__header">
        <el-icon :size="12">
          <ChatLineSquare />
        </el-icon>
        <span>引用回复</span>
        <button class="afc-quote-preview__close" @click="emit('clear-quote')">
          <el-icon :size="12">
            <Close />
          </el-icon>
        </button>
      </div>
      <div class="afc-quote-preview__content">
        <MdPreview
          :modelValue="getQuotePreviewContent(quotedMessage)"
          class="afc-md-preview afc-quote-md"
        />
      </div>
    </div>
  </Transition>

  <Transition name="afc-fade">
    <div v-if="attachedFile" class="afc-quote-preview afc-attached-file">
      <div class="afc-quote-preview__header">
        <el-icon :size="12">
          <Document />
        </el-icon>
        <span>参考文档：{{ attachedFile.filename }}（{{ attachedFile.char_count }} 字）</span>
        <button class="afc-quote-preview__close" title="移除该文档" @click="attachedFile = null">
          <el-icon :size="12">
            <Close />
          </el-icon>
        </button>
      </div>
      <div class="afc-file-snippet">
        {{ attachedFile.content.slice(0, 160) }}{{ attachedFile.content.length > 160 ? "..." : "" }}
      </div>
    </div>
  </Transition>

  <footer
    class="afc-footer"
    @paste="handlePaste"
    @drop.prevent="handleDrop"
    @dragover.prevent
  >
    <el-select
      v-if="reasoningOptions.length"
      :model-value="reasoningEffort"
      placeholder="思考强度"
      size="small"
      class="afc-effort-select"
      @update:model-value="emit('update:reasoningEffort', $event || null)"
    >
      <template #prefix>
        <el-icon :size="13">
          <MagicStick />
        </el-icon>
      </template>
      <el-option
        v-for="option in reasoningOptions"
        :key="option.value"
        :label="option.label"
        :value="option.value"
      />
    </el-select>
    <el-input
      :ref="setInputRef"
      :model-value="inputText"
      type="textarea"
      :autosize="{ minRows: 1, maxRows: 4 }"
      :placeholder="placeholder"
      :disabled="isLoading"
      class="afc-input"
      resize="none"
      @update:model-value="emit('update:inputText', $event)"
      @keydown.enter.exact.prevent="onSend()"
      @keydown.shift.enter.exact="() => {}"
    />
    <el-button
      v-if="isLoading"
      class="afc-send-btn afc-send-btn--stop"
      circle
      @click="emit('stop')"
    >
      <el-icon :size="16">
        <VideoPause />
      </el-icon>
    </el-button>
    <el-button
      v-else
      class="afc-send-btn"
      :disabled="!canSend"
      circle
      @click="onSend()"
    >
      <el-icon :size="16">
        <Promotion />
      </el-icon>
    </el-button>
  </footer>

  <p class="afc-caption">Enter 发送 &nbsp;·&nbsp; Shift+Enter 换行</p>
</template>

<script setup lang="ts">
import {
  ChatLineSquare,
  Close,
  DataBoard,
  Document,
  MagicStick,
  Paperclip,
  Promotion,
  VideoPause,
} from "@element-plus/icons-vue";
import { computed, nextTick, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { MdPreview } from "@/utils/md-editor-v3";
import {
  commonFileApi,
  COMMON_FILE_ACCEPT,
  COMMON_FILE_EXTENSIONS,
  validateCommonFile,
  type ParsedDocumentVO,
} from "@/api/common";
import type { ChatMessage, KnowledgeLoadStatus, KnowledgeOption } from "../types";

const props = defineProps<{
  inputText: string;
  /** 思考强度（词典 reasoning_effort 取值），无词典项时隐藏控件 */
  reasoningEffort: string | null;
  reasoningOptions: { label: string; value: string }[];
  selectedDbIds: string[];
  placeholder: string;
  quickQuestions: string[];
  showQuick: boolean;
  knowledgeList: KnowledgeOption[];
  knowledgeLoading: boolean;
  knowledgeLoadStatus: KnowledgeLoadStatus;
  knowledgeLoadError?: string | null;
  selectedKnowledgeTags: KnowledgeOption[];
  quotedMessage: ChatMessage | null;
  isLoading: boolean;
  getQuotePreviewContent: (msg: ChatMessage) => string;
}>();

const emit = defineEmits<{
  (e: "update:inputText", value: string): void;
  (e: "update:reasoningEffort", value: string | null): void;
  (e: "update:selectedDbIds", value: string[]): void;
  (e: "input-ready", instance: any): void;
  (e: "send", text?: string): void;
  (e: "stop"): void;
  (e: "clear-quote"): void;
  (e: "remove-selected-db", id: string): void;
  (e: "knowledge-dropdown-open"): void;
}>();

const parsingFile = ref(false);
const attachedFile = ref<ParsedDocumentVO | null>(null);

const canSend = computed(() => !!props.inputText.trim() || !!attachedFile.value);

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
    attachedFile.value = parsed;
    ElMessage.success(
      `已解析「${parsed.filename}」（共 ${parsed.char_count} 字），发送时将一并作为参考内容提交`
    );
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

function onSend(quickText?: string) {
  if (props.isLoading) return;
  const baseText = (quickText ?? props.inputText).trim();
  if (!baseText && !attachedFile.value) return;

  let fullText = baseText;
  if (attachedFile.value) {
    const docBlock = `【参考文档：${attachedFile.value.filename}】\n${attachedFile.value.content}`;
    fullText = baseText ? `${baseText}\n\n---\n${docBlock}` : `请阅读并分析以下参考文档：\n\n${docBlock}`;
    attachedFile.value = null;
  }
  emit("send", fullText);
}

const knowledgeNoDataText = computed(() => {
  if (props.knowledgeLoadStatus === "idle") return "点击后加载知识库";
  if (props.knowledgeLoadStatus === "error") return "加载失败，请重新打开重试";
  return "暂无知识库";
});

let inputInstance: any = null;

function handleKnowledgeVisibleChange(visible: boolean): void {
  if (visible) emit("knowledge-dropdown-open");
}

function setInputRef(el: any): void {
  inputInstance = el;
  emit("input-ready", el);
}

onMounted(() => {
  nextTick(() => emit("input-ready", inputInstance));
});
</script>

<style src="../styles/AiChatComposer.css"></style>
