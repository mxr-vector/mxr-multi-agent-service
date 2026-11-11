/**
 * 剧本 AI 创作会话状态编排（story-ai-workspace）。
 *
 * 收口右栏抽屉的有状态逻辑：会话列表/切换/删除、消息流回放、SSE 流式
 * 生成与中断、生成表单状态（制作参数记忆预填）。组件只做呈现。
 */
import { computed, onScopeDispose, ref, shallowRef, watch, type Ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  storyAiApi,
  storyFileUrl,
  type StoryCharacterCard,
  type StoryKeyframeCard,
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

/** 消息上的关键帧数据读取 */
export function readKeyframe(message: StoryMessageVO): StoryKeyframeCard | null {
  const kf = (message.params ?? {})["keyframe_data"];
  return kf && typeof kf === "object" ? (kf as StoryKeyframeCard) : null;
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
  const form = ref<StoryGeneratePayload>({
    idea: "",
    style_key: "",
    aspect_ratio: "16:9",
    episodes: null,
    episode_duration: 30,
    tone: null,
  });

  // ---------- 流式状态 ----------
  const streaming = shallowRef(false);
  const streamText = shallowRef("");
  let abortStream: (() => void) | null = null;

  // ---------- 消息级辅助操作（重新编辑/重新生成/断点续写） ----------
  const rewriteTarget = shallowRef<StoryMessageVO | null>(null);
  let formBeforeRewrite: StoryGeneratePayload | null = null;

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

  async function loadMessages(silent = false) {
    if (!activeSessionId.value) {
      messages.value = [];
      return;
    }
    if (!silent) {
      loadingMessages.value = true;
    }
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
      if (!silent) {
        loadingMessages.value = false;
      }
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
      form.value.aspect_ratio = (params.aspect_ratio as string) ?? "16:9";
      form.value.episodes = (params.episodes as number) ?? null;
      form.value.episode_duration = (params.episode_duration as number) ?? 30;
      form.value.tone = (params.tone as string) ?? null;
    } else if (styles.value.length && !form.value.style_key) {
      form.value.style_key = styles.value[0].key;
      const ratios = styles.value[0].aspect_ratios ?? [];
      form.value.aspect_ratio = ratios.includes("16:9") ? "16:9" : ratios[0] ?? "16:9";
      form.value.episode_duration = 30;
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
    cancelRewrite();
    activeSessionId.value = id;
    await loadMessages();
  }

  async function createSession(title?: string) {
    cancelRewrite();
    const res = await storyAiApi.createSession(projectId.value, title);
    await loadSessions();
    activeSessionId.value = res.data.id;
    messages.value = [];
    return res.data;
  }

  async function removeSession(id: string) {
    cancelRewrite();
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

  /** 重新编辑用户问题：回填正文与制作参数（参考图由表单组件回填） */
  function beginRewrite(message: StoryMessageVO) {
    if (streaming.value || message.role !== "user") return;
    const params = (message.params ?? {}) as Record<string, unknown>;
    // art 等其它用户消息没有制作参数快照，不能按剧本问题重新编辑
    if (typeof params.style_key !== "string" || !params.style_key) return;
    if (!rewriteTarget.value) {
      formBeforeRewrite = { ...form.value, images: [...(form.value.images ?? [])] };
    }
    rewriteTarget.value = message;
    const storedDuration = params.episode_duration;
    const primaryImage =
      message.image_file ??
      (typeof params.image_file === "string" ? params.image_file : null);
    const restoredImages = Array.isArray(params.images)
      ? params.images.filter((img): img is string => typeof img === "string" && !!img)
      : [];
    if (primaryImage && !restoredImages.includes(primaryImage)) {
      restoredImages.unshift(primaryImage);
    }
    form.value = {
      idea: message.content ?? "",
      style_key:
        typeof params.style_key === "string" ? params.style_key : form.value.style_key,
      aspect_ratio:
        typeof params.aspect_ratio === "string"
          ? params.aspect_ratio
          : form.value.aspect_ratio,
      episodes: typeof params.episodes === "number" ? params.episodes : null,
      episode_duration:
        storedDuration === 15 || storedDuration === 30
          ? storedDuration
          : form.value.episode_duration ?? 30,
      tone: typeof params.tone === "string" ? params.tone : null,
      mode: typeof params.mode === "string" ? params.mode : form.value.mode,
      image_file: primaryImage,
      images: restoredImages,
    };
  }

  /** 取消重新编辑：还原进入编辑前的表单 */
  function cancelRewrite() {
    rewriteTarget.value = null;
    if (formBeforeRewrite) {
      form.value = formBeforeRewrite;
      formBeforeRewrite = null;
    }
  }

  /** 会话切换时丢弃重编辑目标（不回填表单，表单由 init/用户操作接管） */
  function resetRewriteState() {
    rewriteTarget.value = null;
    formBeforeRewrite = null;
  }

  async function confirmOverwrite(message: string): Promise<boolean> {
    try {
      await ElMessageBox.confirm(message, "覆盖对话", {
        type: "warning",
        confirmButtonText: "继续",
        cancelButtonText: "取消",
      });
      return true;
    } catch {
      return false;
    }
  }

  /** 本地消息序号：覆盖/重生成后取剩余消息最大值 + 1 */
  function nextLocalSequence(): number {
    return messages.value.reduce((max, m) => Math.max(max, m.sequence), -1) + 1;
  }

  /** 本地先行渲染 user 消息（结束后以服务端回放为准） */
  function pushLocalUser(
    sessionId: string,
    payload: StoryGeneratePayload,
    sequence: number
  ) {
    const images = payload.images?.length ? [...payload.images] : [];
    const styleName = styles.value.find((s) => s.key === payload.style_key)?.name;
    messages.value.push({
      id: `local-user-${Date.now()}`,
      session_id: sessionId,
      role: "user",
      kind: "general",
      content: payload.idea,
      image_file: payload.image_file ?? null,
      prompt: null,
      params: {
        style_key: payload.style_key,
        style_name: styleName,
        aspect_ratio: payload.aspect_ratio,
        episodes: payload.episodes,
        tone: payload.tone,
        episode_duration: payload.episode_duration,
        mode: payload.mode,
        image_file: payload.image_file ?? null,
        images,
      },
      sequence,
      status: "done",
      error: null,
      created_at: new Date().toISOString(),
    });
  }

  /** 共享流式消费：answer 增量累积，结束/失败统一收口并回放服务端状态 */
  async function runStream(
    sessionId: string,
    payload: StoryGeneratePayload,
    restoreIdea?: string,
    onProjectChanged?: () => void
  ) {
    streaming.value = true;
    streamText.value = "";
    const parts: string[] = [];
    const abort = await storyAiApi.generate(
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
        // 若尚未收到任何生成内容就失败，恢复输入框内容，避免用户输入的提示词丢失
        if (parts.length === 0 && restoreIdea && !form.value.idea) {
          form.value.idea = restoreIdea;
        }
        ElMessage.error(error.message || "生成失败");
        await loadMessages();
      },
      async () => {
        finishStream();
        await loadMessages(true);
        onProjectChanged?.();
      }
    );
    // 请求在返回前即失败时 onError 已复位，避免把旧中止函数重新挂回
    if (streaming.value) {
      abortStream = abort;
    }
  }

  /** 发起流式生成：新增一轮，或对已选中的用户问题执行覆盖式重编辑 */
  async function send(onProjectChanged?: () => void) {
    const idea = (form.value.idea ?? "").trim();
    const target = rewriteTarget.value;
    if (!idea) {
      ElMessage.warning(target ? "请先编辑问题内容" : "请先描述创作需求");
      return;
    }
    if (idea.length > 20000) {
      ElMessage.warning(`创作需求长度（${idea.length}字）已超出上限（20000字），请适当精简`);
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
    if (!sessionId) return;

    let payload: StoryGeneratePayload;
    let sequence: number;
    if (target) {
      const confirmed = await confirmOverwrite(
        "重新编辑将覆盖该问题及其后的对话（已沉淀资产不受影响），确定发送？"
      );
      if (!confirmed) return;
      const index = messages.value.findIndex((m) => m.id === target.id);
      if (index >= 0) messages.value.splice(index);
      payload = {
        ...form.value,
        idea,
        action: "rewrite",
        target_message_id: target.id,
      };
      sequence = target.sequence;
      rewriteTarget.value = null;
      formBeforeRewrite = null;
    } else {
      payload = { ...form.value, idea };
      sequence = nextLocalSequence();
    }

    pushLocalUser(sessionId, payload, sequence);
    form.value = { ...form.value, idea: "", image_file: null, images: [] };
    await runStream(sessionId, payload, idea, onProjectChanged);
  }

  /** 重新生成：删除该回答及其后消息，复用原用户问题重跑 */
  async function regenerate(message: StoryMessageVO, onProjectChanged?: () => void) {
    if (streaming.value || message.status === "generating") return;
    const sessionId = activeSessionId.value;
    const index = messages.value.findIndex((m) => m.id === message.id);
    if (!sessionId || index < 0) return;
    const confirmed = await confirmOverwrite(
      "重新生成将覆盖该回答及其后的对话（已沉淀资产不受影响），确定？"
    );
    if (!confirmed) return;
    const question = [...messages.value.slice(0, index)]
      .reverse()
      .find((m) => m.role === "user");
    if (!question) {
      ElMessage.warning("未找到该回答对应的用户问题");
      return;
    }
    messages.value.splice(index);
    await runStream(
      sessionId,
      {
        ...form.value,
        idea: question?.content ?? "",
        action: "regenerate",
        target_message_id: message.id,
      },
      undefined,
      onProjectChanged
    );
  }

  /** 断点续写：复用被停止/失败的回答，保留半截内容继续生成 */
  async function continueGeneration(
    message: StoryMessageVO,
    onProjectChanged?: () => void
  ) {
    if (streaming.value) return;
    if (message.status !== "stopped" && message.status !== "failed") return;
    const sessionId = activeSessionId.value;
    const index = messages.value.findIndex((m) => m.id === message.id);
    if (!sessionId || index < 0) return;
    if (index < messages.value.length - 1) {
      const confirmed = await confirmOverwrite("续写将清理该回答之后的消息，确定？");
      if (!confirmed) return;
      messages.value.splice(index + 1);
    }
    const question = [...messages.value.slice(0, index)]
      .reverse()
      .find((m) => m.role === "user");
    if (!question) {
      ElMessage.warning("未找到该回答对应的用户问题");
      return;
    }
    message.status = "generating";
    message.error = null;
    await runStream(
      sessionId,
      {
        ...form.value,
        idea: question?.content ?? "",
        action: "continue",
        target_message_id: message.id,
      },
      undefined,
      onProjectChanged
    );
  }

  async function stop() {
    if (!activeSessionId.value) return;
    abortStream?.();
    abortStream = null;
    streaming.value = false;
    streamText.value = "";
    await storyAiApi.stop(activeSessionId.value).catch(() => null);
    await loadMessages(true);
  }

  /** 会话消息刷新（卡片沉淀/立绘回填后由组件触发，静默无感） */
  async function refresh() {
    await loadMessages(true);
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
    resetRewriteState();
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
    // 消息级辅助操作
    rewriteTarget,
    beginRewrite,
    cancelRewrite,
    regenerate,
    continueGeneration,
    // 初始化
    init,
    storyFileUrl,
  };
}
