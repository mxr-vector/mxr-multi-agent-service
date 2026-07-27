import { computed, nextTick, type Ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { AiSessionApi } from "@/api/datas/ai";
import type { SessionMessageVO, SessionVO } from "@/api/datas/ai";
import { KnowledgeApi } from "@/api/datas/database";
import { AiTagApi } from "@/api/datas/label";
import {
  BACKEND_MSG_TYPE,
  MSG_STATUS,
  SESSION_TITLE_ELLIPSIS,
  SESSION_TITLE_MAX_LEN,
} from "../constants";
import type {
  AiTagOption,
  ChatMessage,
  ChatSession,
  KnowledgeOption,
  MessageRole,
  MessageStatus,
} from "../types";
import { formatDate, makeWelcome, normalizeSources, splitThinkContent } from "../utils/chatMessage";

interface UseAiChatHistoryDeps {
  messages: Ref<ChatMessage[]>;
  inputText: Ref<string>;
  quotedMessage: Ref<ChatMessage | null>;
  selectedDbIds: Ref<number[]>;
  selectedTagIds: Ref<number[]>;
  knowledgeList: Ref<KnowledgeOption[]>;
  tagList: Ref<AiTagOption[]>;
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
    selectedTagIds,
    knowledgeList,
    tagList,
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
      const res: any = await KnowledgeApi.getKnowledgeList();
      const list = res.data?.rows || res.rows || res.data || [];
      knowledgeList.value = (Array.isArray(list) ? list : []).map((kb: any) => ({
        label: kb.name,
        value: kb.id,
      }));
    } catch (error) {
      knowledgeList.value = [];
      throw error;
    }
  }

  async function loadTagList(): Promise<void> {
    try {
      const res: any = await AiTagApi.getAiTagList();
      const list = res.data?.rows || res.rows || res.data || [];
      tagList.value = (Array.isArray(list) ? list : [])
        .map((tag: any) => ({
          label: String(tag.name ?? ""),
          value: Number(tag.id),
        }))
        .filter((tag: AiTagOption) => Number.isFinite(tag.value));
    } catch (error) {
      tagList.value = [];
      throw error;
    }
  }

  async function loadSessions(): Promise<void> {
    try {
      const res: any = await AiSessionApi.getSessionList();
      const list = res.data || res || [];
      const sessionList = Array.isArray(list) ? list : [];

      sessions.value = sessionList.map((s: SessionVO) => {
        const rawTitle = (s.title || s.summary || "").trim();
        const title = rawTitle
          ? rawTitle.length > SESSION_TITLE_MAX_LEN
            ? rawTitle.slice(0, SESSION_TITLE_MAX_LEN) + SESSION_TITLE_ELLIPSIS
            : rawTitle
          : `新会话 (${s.messageCount}条)`;
        return {
          id: s.sessionId,
          title,
          messages: [],
          createdAt: new Date(s.createTime).getTime(),
        };
      });
    } catch {
      sessions.value = [];
    }
  }

  async function loadSession(session: ChatSession): Promise<void> {
    try {
      const res: any = await AiSessionApi.getSessionMessages(session.id);
      const msgList = res.data || res || [];
      messages.value = [
        makeWelcome(),
        ...(Array.isArray(msgList) ? msgList : []).map((m: SessionMessageVO) => {
          const sources = normalizeSources(m);
          const role = (
            m.messageType === BACKEND_MSG_TYPE.USER ? "user" : "assistant"
          ) as MessageRole;
          const parsedContent =
            role === "assistant"
              ? splitThinkContent(m.content ?? "")
              : { content: m.content ?? "" };

          return {
            id: String(m.id),
            role,
            content: parsedContent.content,
            time: new Date(m.createTime).toLocaleTimeString("zh-CN", {
              hour: "2-digit",
              minute: "2-digit",
            }),
            status: MSG_STATUS.DONE as MessageStatus,
            ...(parsedContent.thinking ? { thinking: parsedContent.thinking } : {}),
            ...(sources.length ? { sources } : {}),
          };
        }),
      ];
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
      await AiSessionApi.deleteSession(id);
      sessions.value = sessions.value.filter((s) => s.id !== id);
      if (currentSessionId.value === id) await handleCreateSession();
    } catch {}
  }

  async function handleDeleteAllSessions(): Promise<void> {
    try {
      await ElMessageBox.confirm("确定清空所有历史会话吗？此操作不可恢复。", "提示", {
        confirmButtonText: "清空",
        cancelButtonText: "取消",
        type: "warning",
      });
      await AiSessionApi.deleteAllSessions();
      sessions.value = [];
      await handleCreateSession();
    } catch {}
  }

  function newSession(): void {
    messages.value = [makeWelcome()];
    currentSessionId.value = null;
    inputText.value = "";
    quotedMessage.value = null;
    thinkingExpanded.clear();
    thinkingTouched.clear();
    nextTick(updateScrollToBottomVisibility);
  }

  async function handleLoadSession(session: ChatSession): Promise<void> {
    await loadSession(session);
  }

  async function handleNewSession(): Promise<void> {
    newSession();
    await loadSessions();
    nextTick(() => inputRef.value?.focus());
  }

  async function handleCreateSession(): Promise<void> {
    const hasUserMessage = messages.value.some((m) => m.role === "user");
    if (messages.value.length <= 1 && !hasUserMessage) {
      inputText.value = "";
      nextTick(() => inputRef.value?.focus());
      return;
    }

    try {
      const res: any = await AiSessionApi.createSession();
      const rawData = res.data ?? res;
      const sessionId = typeof rawData === "string" ? rawData : rawData?.sessionId;
      if (sessionId) {
        currentSessionId.value = sessionId;
        messages.value = [makeWelcome()];
        inputText.value = "";
        quotedMessage.value = null;
        thinkingExpanded.clear();
        thinkingTouched.clear();
        await loadSessions();
        nextTick(() => inputRef.value?.focus());
      } else {
        console.warn("[AiChat] createSession 返回数据异常:", res);
        newSession();
        await loadSessions();
        nextTick(() => inputRef.value?.focus());
      }
    } catch {
      ElMessage.error("创建会话失败");
    }
  }

  const selectedKnowledgeTags = computed(() => {
    const map = new Map(knowledgeList.value.map((db) => [db.value, db]));
    return selectedDbIds.value
      .map((id) => map.get(id))
      .filter((db): db is KnowledgeOption => Boolean(db));
  });

  const selectedTagOptions = computed(() => {
    const map = new Map(tagList.value.map((tag) => [tag.value, tag]));
    return selectedTagIds.value
      .map((id) => map.get(id))
      .filter((tag): tag is AiTagOption => Boolean(tag));
  });

  function removeSelectedDb(id: number): void {
    selectedDbIds.value = selectedDbIds.value.filter((dbId) => dbId !== id);
  }

  function removeSelectedTag(id: number): void {
    selectedTagIds.value = selectedTagIds.value.filter((tagId) => tagId !== id);
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
    loadTagList,
    loadSessions,
    loadSession,
    deleteSession,
    handleDeleteAllSessions,
    newSession,
    handleLoadSession,
    handleNewSession,
    handleCreateSession,
    selectedKnowledgeTags,
    selectedTagOptions,
    removeSelectedDb,
    removeSelectedTag,
    groupedSessions,
  };
}
