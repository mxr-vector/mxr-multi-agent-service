<template>
    <el-scrollbar :ref="setScrollbarRef" class="afc-scrollbar" wrap-class="afc-scroll-wrap" @scroll="hideSourceTooltip">
        <Transition name="afc-fade">
            <div v-if="!currentSessionId && messages.length <= 1" class="afc-empty-state">
                <el-icon :size="48" color="#d1d5db">
                    <ChatDotRound />
                </el-icon>
                <p class="afc-empty-state__text">新对话</p>
                <p class="afc-empty-state__sub">输入问题开始对话，或从历史会话中选择</p>
            </div>
        </Transition>
        <div class="afc-messages">
            <TransitionGroup name="afc-msg">
                <div v-for="msg in messages" :key="msg.id" class="afc-msg" :class="`afc-msg--${msg.role}`"
                    :data-afc-msg-id="msg.id">
                    <div class="afc-msg__ava" :class="`afc-msg__ava--${msg.role}`">
                        <SvgIcon v-if="msg.role === 'user'" name="水豚噜噜" colored :size="26" />
                        <SvgIcon v-else name="智能优化" :size="16" />
                    </div>
                    <div class="afc-msg__body">
                        <div v-if="msg.thinking" class="afc-thinking-card">
                            <div class="afc-thinking-card__hd" @click="emit('toggle-thinking', msg.id)">
                                <el-icon :size="12">
                                    <MagicStick />
                                </el-icon>
                                <span>深度思考过程</span>
                                <el-icon class="afc-thinking-card__arrow"
                                    :class="{ 'is-open': isThinkingExpanded(msg.id) }" :size="11">
                                    <ArrowDown />
                                </el-icon>
                            </div>
                            <Transition name="afc-fade">
                                <div v-if="isThinkingExpanded(msg.id)" class="afc-thinking-card__bd">
                                    <MdPreview :modelValue="msg.thinking" class="afc-md-preview" />
                                </div>
                            </Transition>
                        </div>
                        <div v-if="
                            msg.content || msg.status === MSG_STATUS.TYPING || msg.status === MSG_STATUS.ERROR
                        " class="afc-bubble" :class="{
                'afc-bubble--error': msg.status === MSG_STATUS.ERROR,
                'afc-bubble--typing': msg.status === MSG_STATUS.TYPING && !msg.content,
            }">
                            <span v-if="msg.status === MSG_STATUS.TYPING && !msg.content" class="afc-typing">
                                <span />
                                <span />
                                <span />
                                <span class="afc-typing__timer">{{ elapsedSeconds }}s</span>
                            </span>
                            <template v-else-if="msg.role === 'assistant'">
                                <div @click="handleSourceClick($event, msg)">
                                    <MdPreview :modelValue="getMessageSourceMarkdown(msg)" class="afc-md-preview" />
                                </div>
                            </template>
                            <MdPreview v-else :modelValue="getAnswerContent(msg)" class="afc-md-preview" />
                        </div>
                        <span class="afc-msg__time">{{ msg.time }}</span>
                        <div class="afc-msg-actions"
                            v-if="msg.status !== MSG_STATUS.TYPING && msg.id !== messages[0]?.id">
                            <template v-if="msg.role === 'user'">
                                <button class="afc-action-btn" @click="emit('copy', msg)"
                                    :title="copiedMessageId === msg.id ? '已复制' : '复制'">
                                    <el-icon :size="16">
                                        <DocumentCopy v-if="copiedMessageId !== msg.id" />
                                        <Select v-else />
                                    </el-icon>
                                </button>
                                <button class="afc-action-btn" @click="emit('edit', msg)" title="修改"
                                    :disabled="isLoading">
                                    <el-icon :size="16">
                                        <Edit />
                                    </el-icon>
                                </button>
                            </template>
                            <template v-else>
                                <button class="afc-action-btn" @click="emit('copy', msg)"
                                    :title="copiedMessageId === msg.id ? '已复制' : '复制'">
                                    <el-icon :size="16">
                                        <DocumentCopy v-if="copiedMessageId !== msg.id" />
                                        <Select v-else />
                                    </el-icon>
                                </button>
                                <button class="afc-action-btn" @click="emit('regenerate', msg)" title="重新生成"
                                    :disabled="isLoading">
                                    <el-icon :size="16">
                                        <RefreshRight />
                                    </el-icon>
                                </button>
                                <button class="afc-action-btn" @click="emit('quote', msg)" title="引用追问"
                                    :disabled="isLoading">
                                    <el-icon :size="16">
                                        <ChatLineSquare />
                                    </el-icon>
                                </button>
                            </template>
                        </div>
                    </div>
                </div>
            </TransitionGroup>
        </div>
    </el-scrollbar>

    <Transition name="afc-fade">
        <button v-if="showScrollToBottom" class="afc-bottom-btn" @click="emit('scroll-to-bottom')" aria-label="滚动到底部"
            title="滚动到底部">
            <el-icon :size="14">
                <Bottom />
            </el-icon>
        </button>
    </Transition>

    <el-tooltip v-if="sourceTooltipVirtualRef" virtual-triggering :virtual-ref="sourceTooltipVirtualRef"
        :visible="sourceTooltipVisible" placement="top" popper-class="afc-source-tooltip"
        :popper-options="sourceTooltipPopperOptions">
        <template #content>
            <MdPreview :modelValue="sourceTooltipMarkdown" class="afc-md-preview afc-source-tooltip__preview" />
        </template>
    </el-tooltip>
</template>

<script setup lang="ts">
import {
    ArrowDown,
    Bottom,
    ChatDotRound,
    ChatLineSquare,
    DocumentCopy,
    Edit,
    MagicStick,
    RefreshRight,
    Select,
} from "@element-plus/icons-vue";
import { nextTick, onMounted, onUnmounted, shallowRef } from "vue";
import { MdPreview } from "@/utils/md-editor-v3";
import { MSG_STATUS } from "../constants";
import type { ChatSource } from "@/api/aichat/ai";
import type { ChatMessage } from "../types";

defineProps<{
    messages: ChatMessage[];
    currentSessionId: string | null;
    elapsedSeconds: number;
    showScrollToBottom: boolean;
    copiedMessageId: string | null;
    isLoading: boolean;
    isThinkingExpanded: (id: string) => boolean;
    getAnswerContent: (msg: ChatMessage) => string;
    getMessageSourceMarkdown: (msg: ChatMessage) => string;
}>();

const emit = defineEmits<{
    (e: "scrollbar-ready", instance: any): void;
    (e: "toggle-thinking", id: string): void;
    (e: "copy", msg: ChatMessage): void;
    (e: "edit", msg: ChatMessage): void;
    (e: "regenerate", msg: ChatMessage): void;
    (e: "quote", msg: ChatMessage): void;
    (e: "scroll-to-bottom"): void;
}>();

const sourceTooltipVisible = shallowRef(false);
const sourceTooltipVirtualRef = shallowRef<HTMLElement | null>(null);
const sourceTooltipMarkdown = shallowRef("");
const sourceTooltipPopperOptions = {
    modifiers: [
        { name: "flip", options: { fallbackPlacements: ["bottom", "right", "left"] } },
        { name: "preventOverflow", options: { boundary: "viewport", padding: 12 } },
    ],
};
const SOURCE_REF_SELECTOR = ".afc-source-ref";
let scrollbarInstance: any = null;

function setScrollbarRef(el: any): void {
    scrollbarInstance = el;
    emit("scrollbar-ready", el);
}

function handleSourceClick(event: MouseEvent, msg: ChatMessage): void {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
        hideSourceTooltip();
        return;
    }
    const clickedSource = getClickedSource(target, msg);
    if (!clickedSource) {
        hideSourceTooltip();
        return;
    }
    sourceTooltipVirtualRef.value = clickedSource.element;
    sourceTooltipMarkdown.value = formatSourceTooltipMarkdown(clickedSource.source);
    sourceTooltipVisible.value = true;
}

function handleDocumentClick(event: MouseEvent): void {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (getClickedSourceElement(target)) return;
    if (target.closest(".afc-source-tooltip")) return;
    hideSourceTooltip();
}

function getClickedSource(
    target: HTMLElement,
    msg: ChatMessage
): { element: HTMLElement; source: ChatSource } | null {
    const sourceEl = getClickedSourceElement(target);
    if (!sourceEl) return null;
    const sourceIndexes = getClickedSourceIndexes(sourceEl);
    const source = sourceIndexes
        .map((index) => msg.sources?.find((item) => item.index === index))
        .find((item): item is ChatSource => Boolean(item));
    return source ? { element: sourceEl, source } : null;
}

function getClickedSourceElement(target: HTMLElement): HTMLElement | null {
    return target.closest<HTMLElement>(SOURCE_REF_SELECTOR);
}

function getClickedSourceIndexes(sourceEl: HTMLElement): number[] {
    const sourceText = sourceEl.dataset.sourceIndex || sourceEl.textContent?.match(/\d+/)?.[0];
    if (!sourceText) return [];
    return [Number(sourceText)].filter(Number.isFinite);
}

function formatSourceTooltipMarkdown(source: ChatSource): string {
    const lines = [`### 来源 [${source.index}]`];
    if (source.documentName) lines.push(`- 文件名：${escapeMarkdownInline(source.documentName)}`);
    if (source.kbName) lines.push(`- 数据库来源：${escapeMarkdownInline(source.kbName)}`);

    const content = getSourceContent(source).trim();
    if (content) lines.push("", "---", "", content);
    return lines.join("\n");
}

function getSourceContent(source: ChatSource): string {
    return source.content || source.contentSnippet || "";
}

function escapeMarkdownInline(value: string): string {
    return value.replace(/([\\`*_{}\[\]()#+\-.!|>])/g, "\\$1");
}

function hideSourceTooltip(): void {
    sourceTooltipVisible.value = false;
}

onMounted(() => {
    document.addEventListener("click", handleDocumentClick);
    nextTick(() => emit("scrollbar-ready", scrollbarInstance));
});

onUnmounted(() => {
    document.removeEventListener("click", handleDocumentClick);
});
</script>

<style src="../styles/AiChatMessageList.css"></style>
