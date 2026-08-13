<template>
  <Transition name="afc-fade">
    <div v-if="showQuick" class="afc-quick">
      <button
        v-for="question in quickQuestions"
        :key="question"
        class="afc-quick__btn"
        @click="emit('send', question)"
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

  <footer class="afc-footer">
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
      @keydown.enter.exact.prevent="emit('send')"
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
      :disabled="!inputText.trim()"
      circle
      @click="emit('send')"
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
  MagicStick,
  Promotion,
  VideoPause,
} from "@element-plus/icons-vue";
import { computed, nextTick, onMounted } from "vue";
import { MdPreview } from "@/utils/md-editor-v3";
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
