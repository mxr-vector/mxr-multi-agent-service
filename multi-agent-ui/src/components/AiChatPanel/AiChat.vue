<template>
  <Teleport to="body">
    <AiChatTrigger
      :is-panel-open="isPanelOpen"
      :unread-count="unreadCount"
      :trigger-style="triggerStyle"
      :trigger-classes="triggerClasses"
      @fab-pointerdown="handleFabPointerDown"
      @fab-click="handleFabClick"
      @fab-mouseenter="handleFabMouseEnter"
      @fab-mouseleave="handleFabMouseLeave"
    />

    <Transition name="afc-panel">
      <div
        v-if="isPanelOpen"
        class="afc-panel"
        :class="{ 'is-maximized': isMaximized }"
        :style="panelStyle"
        role="dialog"
        aria-label="AI 问答助手"
      >
        <AiChatPanelHeader
          :title="title"
          :is-loading="isLoading"
          :elapsed-seconds="elapsedSeconds"
          :show-history="showHistory"
          :is-maximized="isMaximized"
          :can-clear="canClearMessages"
          @toggle-history="toggleHistory"
          @clear="handleClear"
          @toggle-maximize="toggleMaximize"
          @close="togglePanel"
        />

        <div class="afc-body">
          <Transition name="afc-slide">
            <AiChatHistorySidebar
              v-if="showHistory"
              :sessions="sessions"
              :grouped-sessions="groupedSessions"
              :current-session-id="currentSessionId"
              @create-session="handleNewSession"
              @delete-all="handleDeleteAllSessions"
              @load-session="handleLoadSession"
              @delete-session="deleteSession"
            />
          </Transition>

          <div class="afc-chat-main">
            <AiChatMessageList
              :messages="messages"
              :current-session-id="currentSessionId"
              :elapsed-seconds="elapsedSeconds"
              :show-scroll-to-bottom="showScrollToBottom"
              :copied-message-id="copiedMessageId"
              :is-loading="isLoading"
              :is-thinking-expanded="isThinkingExpanded"
              :get-answer-content="getAnswerContent"
              :get-message-source-markdown="getMessageSourceMarkdown"
              @scrollbar-ready="setScrollbarRef"
              @toggle-thinking="toggleThinking"
              @copy="copyMessage"
              @edit="editMessage"
              @regenerate="regenerateMessage"
              @quote="quoteMessage"
              @scroll-to-bottom="scrollToLatestBottom"
            />

            <AiChatComposer
              :input-text="inputText"
              :reasoning-effort="reasoningEffort"
              :reasoning-options="reasoningOptions"
              :selected-db-ids="selectedDbIds"
              :placeholder="placeholder"
              :quick-questions="quickQuestions"
              :show-quick="showQuick"
              :knowledge-list="knowledgeList"
              :knowledge-loading="knowledgeLoading"
              :knowledge-load-status="knowledgeLoadStatus"
              :knowledge-load-error="knowledgeLoadError"
              :selected-knowledge-tags="selectedKnowledgeTags"
              :quoted-message="quotedMessage"
              :is-loading="isLoading"
              :get-quote-preview-content="getQuotePreviewContent"
              @update:input-text="inputText = $event"
              @update:reasoning-effort="reasoningEffort = $event"
              @update:selected-db-ids="selectedDbIds = $event"
              @input-ready="setInputRef"
              @send="handleSend"
              @stop="stopGeneration"
              @clear-quote="clearQuote"
              @remove-selected-db="removeSelectedDb"
              @knowledge-dropdown-open="handleKnowledgeDropdownOpen"
            />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import AiChatComposer from "./components/AiChatComposer.vue";
import AiChatHistorySidebar from "./components/AiChatHistorySidebar.vue";
import AiChatMessageList from "./components/AiChatMessageList.vue";
import AiChatPanelHeader from "./components/AiChatPanelHeader.vue";
import AiChatTrigger from "./components/AiChatTrigger.vue";
import { useAiChatController } from "./composables/useAiChatController";
import type { AiChatEmit, AiChatProps } from "./types";

const props = withDefaults(defineProps<AiChatProps>(), {
  title: "AI 智能助手",
  placeholder: "输入你的问题… (Enter 发送)",
  quickQuestions: () => ["想了解公司规章制度", "如何提升工作效率？"],
  right: 28,
  bottom: 28,
  kbIds: () => [],
});

const emit = defineEmits<AiChatEmit>();

const {
  scrollbarRef,
  inputRef,
  isPanelOpen,
  showHistory,
  unreadCount,
  isLoading,
  elapsedSeconds,
  isMaximized,
  showScrollToBottom,
  messages,
  inputText,
  reasoningEffort,
  reasoningOptions,
  selectedDbIds,
  knowledgeList,
  knowledgeLoading,
  knowledgeLoadStatus,
  knowledgeLoadError,
  sessions,
  currentSessionId,
  triggerStyle,
  triggerClasses,
  panelStyle,
  showQuick,
  groupedSessions,
  selectedKnowledgeTags,
  handleFabPointerDown,
  handleFabClick,
  handleFabMouseEnter,
  handleFabMouseLeave,
  togglePanel,
  toggleHistory,
  handleSend,
  handleClear,
  stopGeneration,
  toggleMaximize,
  handleLoadSession,
  handleNewSession,
  handleDeleteAllSessions,
  deleteSession,
  toggleThinking,
  isThinkingExpanded,
  getAnswerContent,
  getMessageSourceMarkdown,
  copyMessage,
  editMessage,
  regenerateMessage,
  quoteMessage,
  copiedMessageId,
  scrollToLatestBottom,
  quotedMessage,
  clearQuote,
  getQuotePreviewContent,
  removeSelectedDb,
  handleKnowledgeDropdownOpen,
  canClearMessages,
  open,
  close,
  send,
} = useAiChatController(props, emit);

function setScrollbarRef(instance: any): void {
  scrollbarRef.value = instance;
}

function setInputRef(instance: any): void {
  inputRef.value = instance;
}

defineExpose({ open, close, send, messages, isPanelOpen, isMaximized });
</script>

<style src="./styles/AiChatPanel.css"></style>
