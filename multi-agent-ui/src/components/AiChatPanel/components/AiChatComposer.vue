<template>
    <Transition name="afc-fade">
        <div v-if="showQuick" class="afc-quick">
            <button v-for="question in quickQuestions" :key="question" class="afc-quick__btn"
                @click="emit('send', question)">
                {{ question }}
            </button>
        </div>
    </Transition>

    <div class="afc-toolbar">
        <div class="afc-filter-stack">
            <div class="afc-db-picker">
                <el-select :model-value="selectedDbIds" placeholder="选择知识库" size="small" clearable multiple filterable
                    collapse-tags class="afc-db-select" :loading="knowledgeLoading" loading-text="知识库加载中..."
                    :no-data-text="knowledgeNoDataText" @visible-change="handleKnowledgeVisibleChange"
                    @update:model-value="emit('update:selectedDbIds', $event)">
                    <template #prefix>
                        <el-icon :size="12">
                            <DataBoard />
                        </el-icon>
                    </template>
                    <el-option v-for="db in knowledgeList" :key="db.value" :label="db.label" :value="db.value" />
                </el-select>
                <div v-if="selectedKnowledgeTags.length" class="afc-db-tags">
                    <el-tag v-for="db in selectedKnowledgeTags" :key="db.value" closable size="small" class="afc-db-tag"
                        @close="emit('remove-selected-db', db.value)">
                        {{ db.label }}
                    </el-tag>
                </div>
            </div>
            <!-- <div class="afc-db-picker">
        <el-select
          :model-value="selectedTagIds"
          placeholder="选择标签"
          size="small"
          clearable
          multiple
          filterable
          collapse-tags
          class="afc-db-select"
          :loading="tagLoading"
          loading-text="标签加载中..."
          :no-data-text="tagNoDataText"
          @visible-change="handleTagVisibleChange"
          @update:model-value="handleTagModelUpdate"
        >
          <template #prefix>
            <el-icon :size="12">
              <CollectionTag />
            </el-icon>
          </template>
          <el-option
            v-for="tag in tagList"
            :key="tag.value"
            :label="tag.label"
            :value="tag.value"
          />
        </el-select>
        <div v-if="selectedTagOptions.length" class="afc-db-tags">
          <el-tag
            v-for="tag in selectedTagOptions"
            :key="tag.value"
            closable
            size="small"
            class="afc-db-tag"
            @close="emit('remove-selected-tag', tag.value)"
          >
            {{ tag.label }}
          </el-tag>
        </div>
      </div> -->
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
                <MdPreview :modelValue="getQuotePreviewContent(quotedMessage)" class="afc-md-preview afc-quote-md" />
            </div>
        </div>
    </Transition>

    <footer class="afc-footer">
        <button class="afc-tool-btn afc-tool-btn--footer" :class="{ 'is-on': deepThinking }"
            @click="emit('update:deepThinking', !deepThinking)">
            <el-icon :size="13">
                <MagicStick />
            </el-icon>
            <span>深度思考</span>
        </button>
        <el-input :ref="setInputRef" :model-value="inputText" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }"
            :placeholder="placeholder" :disabled="isLoading" class="afc-input" resize="none"
            @update:model-value="emit('update:inputText', $event)" @keydown.enter.exact.prevent="emit('send')"
            @keydown.shift.enter.exact="() => { }" />
        <el-button v-if="isLoading" class="afc-send-btn afc-send-btn--stop" circle @click="emit('stop')">
            <el-icon :size="16">
                <VideoPause />
            </el-icon>
        </el-button>
        <el-button v-else class="afc-send-btn" :disabled="!inputText.trim()" circle @click="emit('send')">
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
    // CollectionTag,
    DataBoard,
    MagicStick,
    Promotion,
    VideoPause,
} from "@element-plus/icons-vue";
import { computed, nextTick, onMounted } from "vue";
import { MdPreview } from "@/utils/md-editor-v3";
import type { AiTagOption, ChatMessage, KnowledgeLoadStatus, KnowledgeOption } from "../types";

const props = defineProps<{
    inputText: string;
    deepThinking: boolean;
    selectedDbIds: number[];
    selectedTagIds: number[];
    placeholder: string;
    quickQuestions: string[];
    showQuick: boolean;
    knowledgeList: KnowledgeOption[];
    tagList: AiTagOption[];
    knowledgeLoading: boolean;
    tagLoading: boolean;
    knowledgeLoadStatus: KnowledgeLoadStatus;
    tagLoadStatus: KnowledgeLoadStatus;
    knowledgeLoadError?: string | null;
    tagLoadError?: string | null;
    selectedKnowledgeTags: KnowledgeOption[];
    selectedTagOptions: AiTagOption[];
    quotedMessage: ChatMessage | null;
    isLoading: boolean;
    getQuotePreviewContent: (msg: ChatMessage) => string;
}>();

const emit = defineEmits<{
    (e: "update:inputText", value: string): void;
    (e: "update:deepThinking", value: boolean): void;
    (e: "update:selectedDbIds", value: number[]): void;
    (e: "update:selectedTagIds", value: number[]): void;
    (e: "input-ready", instance: any): void;
    (e: "send", text?: string): void;
    (e: "stop"): void;
    (e: "clear-quote"): void;
    (e: "remove-selected-db", id: number): void;
    (e: "remove-selected-tag", id: number): void;
    (e: "knowledge-dropdown-open"): void;
    (e: "tag-dropdown-open"): void;
}>();

const knowledgeNoDataText = computed(() => {
    if (props.knowledgeLoadStatus === "idle") return "点击后加载知识库";
    if (props.knowledgeLoadStatus === "error") return "加载失败，请重新打开重试";
    return "暂无知识库";
});

// const tagNoDataText = computed(() => {
//   if (props.tagLoadStatus === "idle") return "点击后加载标签";
//   if (props.tagLoadStatus === "error") return "加载失败，请重新打开重试";
//   return "暂无标签";
// });

let inputInstance: any = null;

function handleKnowledgeVisibleChange(visible: boolean): void {
    if (visible) emit("knowledge-dropdown-open");
}

// function handleTagVisibleChange(visible: boolean): void {
//   if (visible) emit("tag-dropdown-open");
// }

// function toNumberIds(value: unknown): number[] {
//   return (Array.isArray(value) ? value : []).map((id) => Number(id)).filter(Number.isFinite);
// }

// function handleTagModelUpdate(value: unknown): void {
//   emit("update:selectedTagIds", toNumberIds(value));
// }

function setInputRef(el: any): void {
    inputInstance = el;
    emit("input-ready", el);
}

onMounted(() => {
    nextTick(() => emit("input-ready", inputInstance));
});
</script>

<style src="../styles/AiChatComposer.css"></style>
