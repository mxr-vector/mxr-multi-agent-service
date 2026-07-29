import { computed, nextTick, onMounted, onUnmounted, reactive, ref, shallowRef } from "vue";
import { useDictStore } from "@/stores/dictStore";
import { useAiChatConversation } from "./useAiChatConversation";
import { useAiChatHistory } from "./useAiChatHistory";
import { useAiChatOptionsLoader } from "./useAiChatOptionsLoader";
import { useAiChatPanelLayout } from "./useAiChatPanelLayout";
import { useAiChatTriggerPosition } from "./useAiChatTriggerPosition";
import { makeWelcome } from "../utils/chatMessage";
import { REASONING_EFFORT_DICT_TYPE } from "../constants";
import type { AiChatEmit, AiChatProps, ChatMessage, ChatSession, KnowledgeOption } from "../types";

export function useAiChatController(props: Readonly<AiChatProps>, emit: AiChatEmit) {
  const scrollbarRef = shallowRef<any>(null);
  const inputRef = shallowRef<any>(null);
  const thinkingExpanded = reactive<Map<string, boolean>>(new Map());
  const thinkingTouched = reactive<Set<string>>(new Set());

  const messages = ref<ChatMessage[]>([makeWelcome()]);
  const inputText = shallowRef<string>("");
  const isLoading = shallowRef<boolean>(false);
  const unreadCount = shallowRef<number>(0);
  const isPanelOpen = shallowRef<boolean>(false);
  const elapsedSeconds = shallowRef<number>(0);
  const showScrollToBottom = shallowRef<boolean>(false);
  const selectedDbIds = ref<string[]>([]);
  const knowledgeList = ref<KnowledgeOption[]>([]);
  const sessions = ref<ChatSession[]>([]);
  const currentSessionId = ref<string | null>(null);
  const copiedMessageId = ref<string | null>(null);
  const quotedMessage = ref<ChatMessage | null>(null);
  const trigger = useAiChatTriggerPosition(props, isPanelOpen, togglePanel);
  const panel = useAiChatPanelLayout(trigger.triggerPosition, isPanelOpen);

  // 思考强度：选项来自词典 reasoning_effort（字典管理页维护，无硬编码回退）
  const dictStore = useDictStore();
  const reasoningEffort = ref<string | null>(null);
  const reasoningOptions = computed(() =>
    dictStore
      .getOptions(REASONING_EFFORT_DICT_TYPE)
      .map((d) => ({ label: d.label, value: d.value }))
  );
  dictStore
    .ensureLoaded()
    .then(() => {
      // 初始选中词典默认项；无默认项时不传，由后端用缺省强度
      if (reasoningEffort.value === null) {
        reasoningEffort.value =
          dictStore.getOptions(REASONING_EFFORT_DICT_TYPE).find((d) => d.is_default)?.value ?? null;
      }
    })
    .catch(() => {});

  let history!: ReturnType<typeof useAiChatHistory>;
  const conversation = useAiChatConversation({
    props,
    emit,
    scrollbarRef,
    inputRef,
    messages,
    inputText,
    isLoading,
    unreadCount,
    elapsedSeconds,
    showScrollToBottom,
    reasoningEffort,
    selectedDbIds,
    quotedMessage,
    copiedMessageId,
    currentSessionId,
    responsiveHeight: panel.responsiveHeight,
    thinkingExpanded,
    thinkingTouched,
    loadSessions: () => history.loadSessions(),
  });

  history = useAiChatHistory({
    messages,
    inputText,
    quotedMessage,
    selectedDbIds,
    knowledgeList,
    sessions,
    currentSessionId,
    thinkingExpanded,
    thinkingTouched,
    inputRef,
    updateScrollToBottomVisibility: conversation.updateScrollToBottomVisibility,
    bindScrollWrap: conversation.bindScrollWrap,
    scrollToBottom: conversation.scrollToBottom,
  });

  const optionsLoader = useAiChatOptionsLoader({
    loadKnowledgeList: history.loadKnowledgeList,
  });
  const showQuick = computed(() => messages.value.length <= 1 && props.quickQuestions!.length > 0);
  const canClearMessages = computed(() => messages.value.length > 1);

  function toggleHistory(): void {
    panel.showHistory.value = !panel.showHistory.value;
  }

  async function togglePanel(): Promise<void> {
    isPanelOpen.value = !isPanelOpen.value;
    if (isPanelOpen.value) {
      unreadCount.value = 0;
      await history.loadSessions();
      if (!isLoading.value && !currentSessionId.value && sessions.value.length > 0) {
        await history.loadSession(sessions.value[0]!);
      }
      nextTick(() => {
        conversation.bindScrollWrap();
        conversation.scrollToBottom();
        inputRef.value?.focus();
      });
      emit("open");
    } else {
      quotedMessage.value = null;
      emit("close");
    }
  }

  function handleWindowResize(): void {
    trigger.keepFabInViewport();
    panel.calcResponsiveSize();
  }

  onMounted(() => {
    trigger.initFabPosition();
    panel.calcResponsiveSize();
    window.addEventListener("resize", handleWindowResize);
  });

  onUnmounted(() => {
    conversation.cleanupConversation();
    trigger.cleanupTrigger();
    window.removeEventListener("resize", handleWindowResize);
  });

  return {
    scrollbarRef,
    inputRef,
    isPanelOpen,
    showHistory: panel.showHistory,
    isFabDragging: trigger.isFabDragging,
    unreadCount,
    isLoading,
    elapsedSeconds,
    isMaximized: panel.isMaximized,
    showScrollToBottom,
    messages,
    inputText,
    reasoningEffort,
    reasoningOptions,
    selectedDbIds,
    knowledgeList,
    knowledgeLoading: optionsLoader.knowledgeLoading,
    knowledgeLoadStatus: optionsLoader.knowledgeLoadStatus,
    knowledgeLoadError: optionsLoader.knowledgeLoadError,
    sessions,
    currentSessionId,
    triggerStyle: trigger.triggerStyle,
    triggerClasses: trigger.triggerClasses,
    panelStyle: panel.panelStyle,
    showQuick,
    selectedKnowledgeTags: history.selectedKnowledgeTags,
    groupedSessions: history.groupedSessions,
    handleFabPointerDown: trigger.handleFabPointerDown,
    handleFabClick: trigger.handleFabClick,
    handleFabMouseEnter: trigger.handleFabMouseEnter,
    handleFabMouseLeave: trigger.handleFabMouseLeave,
    togglePanel,
    toggleHistory,
    handleSend: conversation.handleSend,
    handleClear: conversation.handleClear,
    stopGeneration: conversation.stopGeneration,
    toggleMaximize: panel.toggleMaximize,
    handleLoadSession: history.handleLoadSession,
    handleNewSession: history.handleNewSession,
    handleDeleteAllSessions: history.handleDeleteAllSessions,
    deleteSession: history.deleteSession,
    toggleThinking: conversation.toggleThinking,
    isThinkingExpanded: conversation.isThinkingExpanded,
    getAnswerContent: conversation.getAnswerContent,
    getMessageSourceMarkdown: conversation.getMessageSourceMarkdown,
    copyMessage: conversation.copyMessage,
    editMessage: conversation.editMessage,
    regenerateMessage: conversation.regenerateMessage,
    quoteMessage: conversation.quoteMessage,
    copiedMessageId,
    scrollToLatestBottom: conversation.scrollToLatestBottom,
    quotedMessage,
    clearQuote: conversation.clearQuote,
    getQuotePreviewContent: conversation.getQuotePreviewContent,
    removeSelectedDb: history.removeSelectedDb,
    handleKnowledgeDropdownOpen: optionsLoader.handleKnowledgeDropdownOpen,
    canClearMessages,
    open: () => {
      if (!isPanelOpen.value) togglePanel();
    },
    close: () => {
      if (isPanelOpen.value) togglePanel();
    },
    send: conversation.handleSend,
  };
}
