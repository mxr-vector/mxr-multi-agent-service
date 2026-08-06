import { nextTick, type Ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { AiChatApi, AiSessionApi } from "@/api/aichat";
import type { ChatCompletionPayload, ChatStreamEvent, SseEventMap } from "@/api/aichat";
import { MESSAGE_STATUS, type AiChatEmit, type AiChatProps, type ChatMessage, type MessageStatus } from "../types";
import {
  getMessageSourceMarkdown,
  makeWelcome,
  normalizeSources,
  timeNow,
  uid,
} from "../utils/chatMessage";
import { clamp } from "../utils/chatViewport";

const STREAM_FOLLOW_DISTANCE = 80;
const BOTTOM_BUTTON_DISTANCE = 12;
const SEND_STATUS_SPACE_MIN = 96;
const SEND_STATUS_SPACE_MAX = 180;
const SEND_STATUS_SPACE_RATIO = 0.28;
// done 后延迟刷新会话列表的等待（首轮标题摘要异步回填）
const TITLE_REFRESH_DELAY = 3000;

interface UseAiChatConversationDeps {
  props: Readonly<AiChatProps>;
  emit: AiChatEmit;
  scrollbarRef: Ref<any>;
  inputRef: Ref<any>;
  messages: Ref<ChatMessage[]>;
  inputText: Ref<string>;
  isLoading: Ref<boolean>;
  unreadCount: Ref<number>;
  elapsedSeconds: Ref<number>;
  showScrollToBottom: Ref<boolean>;
  reasoningEffort: Ref<string | null>;
  selectedDbIds: Ref<string[]>;
  quotedMessage: Ref<ChatMessage | null>;
  copiedMessageId: Ref<string | null>;
  currentSessionId: Ref<string | null>;
  responsiveHeight: Ref<number>;
  thinkingExpanded: Map<string, boolean>;
  thinkingTouched: Set<string>;
  /** SSE 事件名映射（由词典 sse_event 解析，见 useAiChatController.sseEventMap） */
  sseEventMap: Ref<SseEventMap>;
  loadSessions: () => Promise<void>;
}

interface StreamingBuffer {
  message: ChatMessage;
  answer: string;
  thinking: string;
}

export function useAiChatConversation(deps: UseAiChatConversationDeps) {
  const {
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
    responsiveHeight,
    thinkingExpanded,
    thinkingTouched,
    sseEventMap,
    loadSessions,
  } = deps;

  const abortFnRef = { value: null as (() => void) | null };
  const streamingBuffers = new Map<string, StreamingBuffer>();
  let timerInterval: ReturnType<typeof setInterval> | null = null;
  let copiedTimer: ReturnType<typeof setTimeout> | null = null;
  let titleRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  let boundScrollWrap: HTMLElement | null = null;
  let anchorRafId: number | null = null;
  let scrollRafId: number | null = null;
  let streamingFlushRafId: number | null = null;

  function startTimer(): void {
    elapsedSeconds.value = 0;
    timerInterval = setInterval(() => {
      elapsedSeconds.value++;
    }, 1000);
  }

  function stopTimer(): void {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
    elapsedSeconds.value = 0;
  }

  function getScrollWrap(): HTMLElement | null {
    return (
      scrollbarRef.value?.$el?.querySelector(".el-scrollbar__wrap") ?? scrollbarRef.value ?? null
    );
  }

  function isNearBottom(): boolean {
    const wrap = getScrollWrap();
    if (!wrap) return true;
    return wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < STREAM_FOLLOW_DISTANCE;
  }

  function updateScrollToBottomVisibility(): void {
    const wrap = getScrollWrap();
    if (!wrap) {
      showScrollToBottom.value = false;
      return;
    }
    const bottomDistance = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight;
    showScrollToBottom.value =
      wrap.scrollHeight > wrap.clientHeight && bottomDistance > BOTTOM_BUTTON_DISTANCE;
  }

  function handleScroll(): void {
    updateScrollToBottomVisibility();
  }

  function bindScrollWrap(): void {
    // Element Plus recreates the internal wrap when the panel remounts, so bind only the live node.
    const wrap = getScrollWrap();
    if (wrap === boundScrollWrap) return;
    boundScrollWrap?.removeEventListener("scroll", handleScroll);
    boundScrollWrap = wrap;
    boundScrollWrap?.addEventListener("scroll", handleScroll, { passive: true });
    updateScrollToBottomVisibility();
  }

  function unbindScrollWrap(): void {
    boundScrollWrap?.removeEventListener("scroll", handleScroll);
    boundScrollWrap = null;
  }

  function getMessageElement(id: string): HTMLElement | null {
    const wrap = getScrollWrap();
    return wrap?.querySelector<HTMLElement>(`[data-afc-msg-id="${CSS.escape(id)}"]`) ?? null;
  }

  function cancelScheduledAnchor(): void {
    if (anchorRafId !== null) {
      cancelAnimationFrame(anchorRafId);
      anchorRafId = null;
    }
  }

  function scheduleScrollMessageBottomIntoView(id: string): void {
    // Anchor the sent question above the footer status area before the streamed answer grows below it.
    nextTick(() => {
      cancelScheduledAnchor();
      anchorRafId = requestAnimationFrame(() => {
        anchorRafId = null;
        const wrap = getScrollWrap();
        const el = getMessageElement(id);
        if (!wrap || !el) return;
        const statusSpace = clamp(
          Math.floor(wrap.clientHeight * SEND_STATUS_SPACE_RATIO),
          SEND_STATUS_SPACE_MIN,
          SEND_STATUS_SPACE_MAX
        );
        const targetTop = el.offsetTop + el.offsetHeight - wrap.clientHeight + statusSpace;
        wrap.scrollTop = clamp(targetTop, 0, Math.max(0, wrap.scrollHeight - wrap.clientHeight));
        updateScrollToBottomVisibility();
      });
    });
  }

  function cancelScheduledScroll(): void {
    if (scrollRafId !== null) {
      cancelAnimationFrame(scrollRafId);
      scrollRafId = null;
    }
  }

  function scheduleScrollToBottom(options: { force?: boolean } = {}): void {
    // Auto-follow only when the user is already near the bottom; manual scrolling must be respected.
    const shouldScroll = options.force || isNearBottom();
    if (!shouldScroll || scrollRafId !== null) return;
    scrollRafId = requestAnimationFrame(() => {
      scrollRafId = null;
      const wrap = getScrollWrap();
      if (wrap) {
        wrap.scrollTop = wrap.scrollHeight;
        updateScrollToBottomVisibility();
      }
    });
  }

  function scrollToBottom(): void {
    nextTick(() => scheduleScrollToBottom({ force: true }));
  }

  function scrollToLatestBottom(): void {
    scrollToBottom();
  }

  function getStreamingBuffer(message: ChatMessage): StreamingBuffer {
    const existing = streamingBuffers.get(message.id);
    if (existing) return existing;
    const buffer = { message, answer: "", thinking: "" };
    streamingBuffers.set(message.id, buffer);
    return buffer;
  }

  function queueStreamingFlush(message: ChatMessage, type: "answer" | "thinking", text = ""): void {
    // Batch SSE chunks into one DOM update per frame to keep streaming smooth.
    if (!text) return;
    const buffer = getStreamingBuffer(message);
    buffer[type] += text;
    if (streamingFlushRafId !== null) return;
    streamingFlushRafId = requestAnimationFrame(() => {
      streamingFlushRafId = null;
      flushStreamingBuffers();
    });
  }

  function flushStreamingBuffers(): void {
    streamingBuffers.forEach((buffer, id) => {
      if (buffer.thinking) {
        buffer.message.thinking = (buffer.message.thinking || "") + buffer.thinking;
        buffer.thinking = "";
        maybeAutoCollapseThinking(buffer.message);
      }
      if (buffer.answer) {
        buffer.message.content += buffer.answer;
        buffer.answer = "";
        maybeAutoCollapseThinking(buffer.message, true);
      }
      updateScrollToBottomVisibility();
      if (!buffer.answer && !buffer.thinking) streamingBuffers.delete(id);
    });
  }

  function flushStreamingBuffer(message: ChatMessage): void {
    const buffer = streamingBuffers.get(message.id);
    if (!buffer) return;
    if (buffer.thinking) {
      message.thinking = (message.thinking || "") + buffer.thinking;
      buffer.thinking = "";
      maybeAutoCollapseThinking(message);
    }
    if (buffer.answer) {
      message.content += buffer.answer;
      buffer.answer = "";
      maybeAutoCollapseThinking(message, true);
    }
    streamingBuffers.delete(message.id);
  }

  function cancelStreamingFlush(): void {
    if (streamingFlushRafId !== null) {
      cancelAnimationFrame(streamingFlushRafId);
      streamingFlushRafId = null;
    }
    streamingBuffers.clear();
  }

  function maybeAutoCollapseThinking(message: ChatMessage, answerStarted = false): void {
    // Keep thinking open briefly for readability, then collapse unless the user toggled it manually.
    if (!message.thinking || thinkingTouched.has(message.id)) return;
    if (!thinkingExpanded.has(message.id)) thinkingExpanded.set(message.id, true);
    const firstScreenLength = Math.max(260, Math.floor(responsiveHeight.value * 0.9));
    if (answerStarted || message.thinking.length >= firstScreenLength) {
      thinkingExpanded.set(message.id, false);
    }
  }

  function finishGeneration(
    aiMsg: ChatMessage,
    options: { status?: MessageStatus; refreshSessions?: boolean } = {}
  ): void {
    flushStreamingBuffer(aiMsg);
    if (options.status) aiMsg.status = options.status;
    else if (aiMsg.status === MESSAGE_STATUS.TYPING) aiMsg.status = MESSAGE_STATUS.DONE;

    isLoading.value = false;
    stopTimer();
    abortFnRef.value = null;
    updateScrollToBottomVisibility();

    if (options.refreshSessions && currentSessionId.value) {
      loadSessions().catch(() => {});
    }
  }

  function handleStreamEvent(event: ChatStreamEvent, aiMsg: ChatMessage): void {
    // 自动建会话场景：首个 think 帧 / done 帧回传 session_id
    if (event.session_id && !currentSessionId.value) {
      currentSessionId.value = event.session_id;
    }

    if (event.event === sseEventMap.value.THINK) {
      if (event.text) {
        // think 帧为整句进展文本，换行分隔逐条追加
        const buffer = getStreamingBuffer(aiMsg);
        const separator = aiMsg.thinking || buffer.thinking ? "\n" : "";
        queueStreamingFlush(aiMsg, "thinking", separator + event.text);
      }
      return;
    }

    if (event.event === sseEventMap.value.ANSWER) {
      queueStreamingFlush(aiMsg, "answer", event.delta ?? "");
      return;
    }

    if (event.event === sseEventMap.value.SOURCES) {
      aiMsg.sources = normalizeSources(event.sources);
      return;
    }

    if (event.event === sseEventMap.value.ERROR) {
      flushStreamingBuffer(aiMsg);
      aiMsg.content = event.msg || "回答生成失败，请稍后重试";
      finishGeneration(aiMsg, { status: MESSAGE_STATUS.ERROR });
      return;
    }

    if (event.event === sseEventMap.value.DONE) {
      // 流紧接着结束，收尾统一由 onComplete 的 finishGeneration 处理；
      // 这里仅预约延迟刷新，等首轮标题摘要异步回填
      if (titleRefreshTimer) clearTimeout(titleRefreshTimer);
      titleRefreshTimer = setTimeout(() => {
        titleRefreshTimer = null;
        loadSessions().catch(() => {});
      }, TITLE_REFRESH_DELAY);
    }
  }

  async function send(text?: string): Promise<void> {
    const content = (text ?? inputText.value).trim();
    if (!content || isLoading.value) return;

    const userMsg: ChatMessage = {
      id: uid(),
      role: "user",
      content,
      time: timeNow(),
      status: MESSAGE_STATUS.DONE,
    };
    messages.value.push(userMsg);
    inputText.value = "";
    scheduleScrollMessageBottomIntoView(userMsg.id);

    const aiMsg: ChatMessage = {
      id: uid(),
      role: "assistant",
      content: "",
      time: timeNow(),
      status: MESSAGE_STATUS.TYPING,
      thinking: "",
      sources: [],
    };
    messages.value.push(aiMsg);
    const reactiveAiMsg = messages.value[messages.value.length - 1]!;
    scheduleScrollMessageBottomIntoView(userMsg.id);

    isLoading.value = true;
    startTimer();

    try {
      // 检索范围：面板内选中知识库 ∪ 宿主传入的固定范围；空时不传，
      // 由后端按当前用户缺省可见范围解析
      const kbIds = Array.from(new Set([...selectedDbIds.value, ...(props.kbIds ?? [])]));
      const reqData: ChatCompletionPayload = {
        question: content,
        session_id: currentSessionId.value || undefined,
        kb_ids: kbIds.length ? kbIds : undefined,
        use_web_search: false,
        reasoning_effort: reasoningEffort.value || undefined,
      };

      const abortFn = await AiChatApi.chatStream(
        reqData,
        sseEventMap.value,
        (event: ChatStreamEvent) => {
          handleStreamEvent(event, reactiveAiMsg);
        },
        (err: Error) => {
          flushStreamingBuffer(reactiveAiMsg);
          reactiveAiMsg.content = `出错了：${err.message}`;
          reactiveAiMsg.status = MESSAGE_STATUS.ERROR;
          finishGeneration(reactiveAiMsg, { status: MESSAGE_STATUS.ERROR });
        },
        () => {
          finishGeneration(reactiveAiMsg, { refreshSessions: true });
        }
      );
      abortFnRef.value = abortFn;
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        flushStreamingBuffer(reactiveAiMsg);
        reactiveAiMsg.content = `出错了：${err?.message ?? "未知错误"}`;
        reactiveAiMsg.status = MESSAGE_STATUS.ERROR;
        finishGeneration(reactiveAiMsg, { status: MESSAGE_STATUS.ERROR });
      } else {
        flushStreamingBuffer(reactiveAiMsg);
        finishGeneration(reactiveAiMsg);
      }
    }
  }

  function stopGeneration(): void {
    const sessionId = currentSessionId.value;
    const finishLatest = (): void => {
      const latest = messages.value[messages.value.length - 1];
      if (latest?.role === "assistant" && latest.status === MESSAGE_STATUS.TYPING) {
        finishGeneration(latest);
      }
    };
    if (!sessionId) {
      abortFnRef.value?.();
      finishLatest();
      return;
    }
    // 后端取消在途任务后会以 done(stopped) 帧正常收尾，无需本地中断；
    // cancelled=false（后端重启后在途任务丢失等）或 stop 请求失败时回退为本地 abort
    AiChatApi.stop(sessionId)
      .then((res) => {
        if (!res.data?.cancelled) {
          abortFnRef.value?.();
          finishLatest();
        }
      })
      .catch(() => {
        abortFnRef.value?.();
        finishLatest();
      });
  }

  async function handleSend(text?: string): Promise<void> {
    let content = text ?? inputText.value;
    if (!content?.trim()) return;
    if (quotedMessage.value) {
      const raw = quotedMessage.value.content;
      const maxLen = 200;
      const truncated = raw.length > maxLen ? raw.slice(0, maxLen) + "..." : raw;
      const quoted = truncated
        .split("\n")
        .map((line) => `> ${line}`)
        .join("\n");
      content = quoted + "\n\n" + content.trim();
      clearQuote();
    }
    emit("message-sent", content.trim());
    await send(content);
    emit("message-received", messages.value[messages.value.length - 1]!);
  }

  async function handleClear(): Promise<void> {
    try {
      await ElMessageBox.confirm("确定清空当前对话记录吗？", "提示", {
        confirmButtonText: "清空",
        cancelButtonText: "取消",
        type: "warning",
      });
      if (currentSessionId.value) {
        await AiSessionApi.remove(currentSessionId.value);
      }
      messages.value = [makeWelcome()];
      currentSessionId.value = null;
      unreadCount.value = 0;
      thinkingExpanded.clear();
      thinkingTouched.clear();
      updateScrollToBottomVisibility();
      await loadSessions();
    } catch {}
  }

  function getAnswerContent(msg: ChatMessage): string {
    return msg.content;
  }

  function toggleThinking(id: string): void {
    thinkingTouched.add(id);
    thinkingExpanded.set(id, !isThinkingExpanded(id));
  }

  function isThinkingExpanded(id: string): boolean {
    return thinkingExpanded.get(id) ?? false;
  }

  function copyMessage(msg: ChatMessage): void {
    const text = msg.content;
    const doCopy = (): void => {
      if (copiedTimer) clearTimeout(copiedTimer);
      copiedMessageId.value = msg.id;
      ElMessage.success("已复制");
      copiedTimer = setTimeout(() => {
        copiedMessageId.value = null;
      }, 2000);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(text)
        .then(doCopy)
        .catch(() => {
          fallbackCopy(text) && doCopy();
        });
    } else {
      fallbackCopy(text) && doCopy();
    }
  }

  function fallbackCopy(text: string): boolean {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }

  function editMessage(msg: ChatMessage): void {
    if (isLoading.value) return;
    inputText.value = msg.content;
    nextTick(() => inputRef.value?.focus());
  }

  function regenerateMessage(msg: ChatMessage): void {
    if (isLoading.value) return;
    const idx = messages.value.findIndex((m) => m.id === msg.id);
    if (idx < 0) return;
    let userMsg: ChatMessage | null = null;
    for (let i = idx - 1; i >= 0; i--) {
      if (messages.value[i]!.role === "user") {
        userMsg = messages.value[i]!;
        break;
      }
    }
    if (!userMsg) return;
    const userContent = userMsg.content;
    messages.value.splice(idx);
    void send(userContent);
  }

  function quoteMessage(msg: ChatMessage): void {
    quotedMessage.value = msg;
    nextTick(() => inputRef.value?.focus());
  }

  function clearQuote(): void {
    quotedMessage.value = null;
  }

  function getQuotePreviewContent(msg: ChatMessage): string {
    const maxLen = 300;
    const raw = msg.content;
    return raw.length > maxLen ? raw.slice(0, maxLen) + "..." : raw;
  }

  function cleanupConversation(): void {
    if (timerInterval) clearInterval(timerInterval);
    if (copiedTimer) clearTimeout(copiedTimer);
    if (titleRefreshTimer) clearTimeout(titleRefreshTimer);
    cancelStreamingFlush();
    cancelScheduledScroll();
    cancelScheduledAnchor();
    unbindScrollWrap();
  }

  return {
    bindScrollWrap,
    unbindScrollWrap,
    updateScrollToBottomVisibility,
    scrollToBottom,
    scrollToLatestBottom,
    send,
    stopGeneration,
    handleSend,
    handleClear,
    toggleThinking,
    isThinkingExpanded,
    getAnswerContent,
    getMessageSourceMarkdown,
    copyMessage,
    editMessage,
    regenerateMessage,
    quoteMessage,
    clearQuote,
    getQuotePreviewContent,
    cleanupConversation,
  };
}
