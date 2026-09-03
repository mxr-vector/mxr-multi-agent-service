/**
 * 剧本 AI 创作会话状态编排（story-ai-workspace）。
 *
 * 收口右栏抽屉的有状态逻辑：会话列表/切换/删除、消息流回放、SSE 流式
 * 生成与中断、生成表单状态（制作参数记忆预填）。组件只做呈现。
 */
import { computed, onScopeDispose, ref, shallowRef, watch, type Ref } from "vue";
import { ElMessage } from "element-plus";
import {
  storyAiApi,
  storyFileUrl,
  type StoryCharacterCard,
  type StoryGeneratePayload,
  type StoryMessageVO,
  type StorySessionVO,
  type StoryStyleVO,
} from "@/api/story";

/** 消息上的角色卡数据读取 */
export function readCard(message: StoryMessageVO): StoryCharacterCard | null {
  const card = (message.params ?? {})["character_card"];
  return card && typeof card === "object" ? (card as StoryCharacterCard) : null;
}

/** 消息回放单页大小（与后端分页上限一致） */
const MESSAGE_PAGE_SIZE = 100;

export function useStoryAi(projectId: Ref<string>, project: Ref<{ style_key: string | null; production_params: Record<string, unknown> | null } | null>) {
  // ---------- 会话 ----------
  const sessions = ref<StorySessionVO[]>([]);
  const activeSessionId = shallowRef<string>("");
  const loadingSessions = shallowRef(false);

  // ---------- 消息 ----------
  const messages = ref<StoryMessageVO[]>([]);
  const loadingMessages = shallowRef(false);

  // ---------- 生成表单（制作参数记忆） ----------
  const styles = ref<StoryStyleVO[]>([]);
  const form = ref<StoryGeneratePayload>({ idea: "", style_key: "", aspect_ratio: null, episodes: null, tone: null });

  // ---------- 流式状态 ----------
  const streaming = shallowRef(false);
  const streamText = shallowRef("");
  let abortStream: (() => void) | null = null;

  const activeSession = computed(
    () => sessions.value.find((s) => s.id === activeSessionId.value) ?? null
  );

  async function loadSessions() {
    loadingSessions.value = true;
    try {
      const res = await storyAiApi.listSessions(projectId.value, 1, 50);
      sessions.value = res.data?.items ?? [];
    } finally {
      loadingSessions.value = false;
    }
  }

  async function loadMessages() {
    if (!activeSessionId.value) {
      messages.value = [];
      return;
    }
    loadingMessages.value = true;
    try {
      // 回放取末页（最新消息）：长会话若固定取升序首页，超页后新产物永不可见
      const first = await storyAiApi.messages(activeSessionId.value, 1, MESSAGE_PAGE_SIZE);
      const total = first.data?.total ?? 0;
      if (total > MESSAGE_PAGE_SIZE) {
        const last = await storyAiApi.messages(
          activeSessionId.value,
          Math.ceil(total / MESSAGE_PAGE_SIZE),
          MESSAGE_PAGE_SIZE
        );
        messages.value = last.data?.items ?? [];
      } else {
        messages.value = first.data?.items ?? [];
      }
    } finally {
      loadingMessages.value = false;
    }
  }

  /** 初始化：加载风格与最近活跃会话（无会话则展示引导），制作参数记忆预填 */
  async function init() {
    const styleRes = await storyAiApi.styles().catch(() => null);
    styles.value = styleRes?.data ?? [];
    const saved = project.value;
    const savedKey = saved?.style_key || "";
    const params = (saved?.production_params ?? {}) as Record<string, unknown>;
    if (savedKey && styles.value.some((s) => s.key === savedKey)) {
      form.value.style_key = savedKey;
      form.value.aspect_ratio = (params.aspect_ratio as string) ?? null;
      form.value.episodes = (params.episodes as number) ?? null;
      form.value.tone = (params.tone as string) ?? null;
    } else if (styles.value.length && !form.value.style_key) {
      form.value.style_key = styles.value[0].key;
      form.value.aspect_ratio = null;
    }
    await loadSessions();
    const latest = await storyAiApi.latestSession(projectId.value).catch(() => null);
    if (latest?.data?.id) {
      activeSessionId.value = latest.data.id;
      await loadMessages();
    } else {
      activeSessionId.value = "";
      messages.value = [];
    }
  }

  async function switchSession(id: string) {
    if (streaming.value) {
      ElMessage.warning("生成进行中，请先停止再切换会话");
      return;
    }
    activeSessionId.value = id;
    await loadMessages();
  }

  async function createSession(title?: string) {
    const res = await storyAiApi.createSession(projectId.value, title);
    await loadSessions();
    activeSessionId.value = res.data.id;
    messages.value = [];
    return res.data;
  }

  async function removeSession(id: string) {
    await storyAiApi.removeSession(id);
    ElMessage.success("会话已删除");
    if (activeSessionId.value === id) {
      activeSessionId.value = "";
      messages.value = [];
      const latest = await storyAiApi.latestSession(projectId.value).catch(() => null);
      if (latest?.data?.id) {
        activeSessionId.value = latest.data.id;
        await loadMessages();
      }
    }
    await loadSessions();
  }

  /** 复位流式状态（成功/失败/中止统一收口，避免 streaming 卡死锁死输入框） */
  function finishStream() {
    streaming.value = false;
    streamText.value = "";
    abortStream = null;
  }

  /** 发起流式生成：本地先渲染 user 消息 + 占位，结束后以服务端回放为准 */
  async function send(onProjectChanged?: () => void) {
    const idea = (form.value.idea ?? "").trim();
    if (!idea) {
      ElMessage.warning("请先描述创作需求");
      return;
    }
    if (!form.value.style_key) {
      ElMessage.warning("请先选择视频风格");
      return;
    }
    if (!activeSessionId.value) {
      await createSession();
    }
    const sessionId = activeSessionId.value;
    const payload = { ...form.value, idea };
    messages.value.push({
      id: `local-user-${Date.now()}`,
      session_id: sessionId,
      role: "user",
      kind: "general",
      content: idea,
      image_file: null,
      prompt: null,
      params: null,
      sequence: messages.value.length,
      status: "done",
      error: null,
      created_at: new Date().toISOString(),
    });
    form.value = { ...form.value, idea: "" };
    streaming.value = true;
    streamText.value = "";
    const parts: string[] = [];
    abortStream = await storyAiApi.generate(
      sessionId,
      payload,
      (event) => {
        if (event.event === "answer") {
          parts.push(event.delta ?? "");
          streamText.value = parts.join("");
        } else if (event.event === "error") {
          ElMessage.error(event.msg ?? "生成失败");
        } else if (event.event === "done") {
          if (event.done?.cards_ok === false && event.done?.cards_error) {
            ElMessage.warning(`角色卡解析失败：${event.done.cards_error}（剧本已生成）`);
          }
        }
      },
      async (error) => {
        // 请求层失败（非 SSE 响应/reader 异常）：与 onComplete 同口径复位，
        // 否则 streaming 滞留 true锁死输入框，只能手动点停止才能解锁
        finishStream();
        ElMessage.error(error.message || "生成失败");
        await loadMessages();
      },
      async () => {
        finishStream();
        await loadMessages();
        onProjectChanged?.();
      }
    );
  }

  async function stop() {
    if (!activeSessionId.value) return;
    abortStream?.();
    abortStream = null;
    streaming.value = false;
    streamText.value = "";
    await storyAiApi.stop(activeSessionId.value).catch(() => null);
    await loadMessages();
  }

  /** 会话消息刷新（卡片沉淀/立绘回填后由组件触发） */
  async function refresh() {
    await loadMessages();
  }

  /** 项目切换/组件卸载时中止在途流，避免旧流增量写入新视图 */
  function abortActiveStream() {
    abortStream?.();
    finishStream();
  }

  onScopeDispose(() => abortActiveStream());

  watch(projectId, () => {
    if (!projectId.value) return;
    abortActiveStream();
    activeSessionId.value = "";
    messages.value = [];
    void init();
  });

  return {
    // 会话
    sessions,
    activeSessionId,
    activeSession,
    loadingSessions,
    loadSessions,
    switchSession,
    createSession,
    removeSession,
    // 消息
    messages,
    loadingMessages,
    loadMessages,
    refresh,
    // 表单与生成
    styles,
    form,
    streaming,
    streamText,
    send,
    stop,
    // 初始化
    init,
    storyFileUrl,
  };
}
