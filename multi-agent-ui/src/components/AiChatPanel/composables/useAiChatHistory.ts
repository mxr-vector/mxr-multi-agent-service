import { computed, nextTick, type Ref } from "vue";
import { ElMessageBox } from "element-plus";
import { AiSessionApi } from "@/api/aichat";
import type { ChatMessageVO, ChatSessionVO } from "@/api/aichat";
import { knowledgeBaseApi } from "@/api/rag/knowledgeBase";

import { MSG_STATUS, SESSION_TITLE_ELLIPSIS, SESSION_TITLE_MAX_LEN } from "../constants";
import type { ChatMessage, ChatSession, KnowledgeOption, MessageStatus } from "../types";
import { formatDate, makeWelcome, normalizeSources } from "../utils/chatMessage";

/** 会话列表单页拉取量（暂不做滚动分页） */
const SESSION_PAGE_SIZE = 50;
/** 会话消息单页拉取量（暂不做滚动分页） */
const MESSAGE_PAGE_SIZE = 200;

interface UseAiChatHistoryDeps {
  messages: Ref<ChatMessage[]>;
  inputText: Ref<string>;
  quotedMessage: Ref<ChatMessage | null>;
  selectedDbIds: Ref<string[]>;
  knowledgeList: Ref<KnowledgeOption[]>;
  sessions: Ref<ChatSession[]>;
  currentSessionId: Ref<string | null>;
  thinkingExpanded: Map<string, boolean>;
  thinkingTouched: Set<string>;
  inputRef: Ref<any>;
  updateScrollToBottomVisibility: () => void;
  bindScrollWrap: () => void;
  scrollToBottom: () => void;
}

export function useAiChatHistory(deps: UseAiChatHistoryDeps) {
  const {
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
    updateScrollToBottomVisibility,
    bindScrollWrap,
    scrollToBottom,
  } = deps;

  async function loadKnowledgeList(): Promise<void> {
    try {
      const res = await knowledgeBaseApi.list({ page: 1, size: 200 });
      const list = res.data?.items ?? [];
      knowledgeList.value = list.map((kb) => ({
        label: kb.name,
        value: kb.id,
      }));
    } catch (error) {
      knowledgeList.value = [];
      throw error;
    }
  }

  async function loadSessions(): Promise<void> {
    try {
      const res = await AiSessionApi.list(1, SESSION_PAGE_SIZE);
      const list = res.data?.items ?? [];

      sessions.value = list.map((s: ChatSessionVO) => {
        const rawTitle = (s.title || "").trim();
        const title =
          rawTitle.length > SESSION_TITLE_MAX_LEN
            ? rawTitle.slice(0, SESSION_TITLE_MAX_LEN) + SESSION_TITLE_ELLIPSIS
            : rawTitle || "新对话";
        return {
          id: s.id,
          title,
          messages: [],
          createdAt: new Date(s.created_at).getTime(),
        };
      });
    } catch {
      sessions.value = [];
    }
  }

  /** 历史消息转面板消息：失败消息按错误态展示，正文回退错误原因 */
  function toChatMessage(m: ChatMessageVO): ChatMessage {
    const isFailed = m.role === "assistant" && m.status === "failed";
    const content = m.content || (isFailed ? `出错了：${m.error ?? "回答生成失败"}` : "");
    const sources = normalizeSources(m.sources);
    return {
      id: m.id,
      role: m.role,
      content,
      time: new Date(m.created_at).toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
      }),
      status: (isFailed ? MSG_STATUS.ERROR : MSG_STATUS.DONE) as MessageStatus,
      ...(m.thinking ? { thinking: m.thinking } : {}),
      ...(sources.length ? { sources } : {}),
    };
  }

  async function loadSession(session: ChatSession): Promise<void> {
    try {
      const res = await AiSessionApi.messages(session.id, 1, MESSAGE_PAGE_SIZE);
      const msgList = res.data?.items ?? [];
      messages.value = [makeWelcome(), ...msgList.map(toChatMessage)];
      thinkingExpanded.clear();
      thinkingTouched.clear();
      currentSessionId.value = session.id;
      nextTick(() => {
        bindScrollWrap();
        scrollToBottom();
      });
    } catch {}
  }

  async function deleteSession(id: string): Promise<void> {
    try {
      await AiSessionApi.remove(id);
      sessions.value = sessions.value.filter((s) => s.id !== id);
      if (currentSessionId.value === id) newSession();
    } catch {}
  }

  async function handleDeleteAllSessions(): Promise<void> {
    try {
      await ElMessageBox.confirm("确定清空所有历史会话吗？此操作不可恢复。", "提示", {
        confirmButtonText: "清空",
        cancelButtonText: "取消",
        type: "warning",
      });
      await AiSessionApi.removeAll();
      sessions.value = [];
      newSession();
    } catch {}
  }

  /** 新对话：仅重置本地状态，会话由后端在首次发送时自动创建 */
  function newSession(): void {
    messages.value = [makeWelcome()];
    currentSessionId.value = null;
    inputText.value = "";
    quotedMessage.value = null;
    thinkingExpanded.clear();
    thinkingTouched.clear();
    nextTick(() => {
      updateScrollToBottomVisibility();
      inputRef.value?.focus();
    });
  }

  async function handleLoadSession(session: ChatSession): Promise<void> {
    await loadSession(session);
  }

  async function handleNewSession(): Promise<void> {
    newSession();
    await loadSessions();
  }

  const selectedKnowledgeTags = computed(() => {
    const map = new Map(knowledgeList.value.map((db) => [db.value, db]));
    return selectedDbIds.value
      .map((id) => map.get(id))
      .filter((db): db is KnowledgeOption => Boolean(db));
  });

  function removeSelectedDb(id: string): void {
    selectedDbIds.value = selectedDbIds.value.filter((dbId) => dbId !== id);
  }

  const groupedSessions = computed(() => {
    const map = new Map<string, ChatSession[]>();
    for (const s of sessions.value) {
      const label = formatDate(s.createdAt);
      if (!map.has(label)) map.set(label, []);
      map.get(label)!.push(s);
    }
    return Array.from(map.entries()).map(([label, items]) => ({ label, items }));
  });

  return {
    loadKnowledgeList,
    loadSessions,
    loadSession,
    deleteSession,
    handleDeleteAllSessions,
    newSession,
    handleLoadSession,
    handleNewSession,
    selectedKnowledgeTags,
    removeSelectedDb,
    groupedSessions,
  };
}
