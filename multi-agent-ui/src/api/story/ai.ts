/**
 * 剧本 AI 生成接口：生成会话、流式生成（SSE）、立绘生成与产物沉淀。
 *
 * SSE 解析对齐 src/api/aichat/ai.ts 的 fetch-stream 模式（事件名直接使用
 * 协议默认值，与后端 sse_event 字典同步的 value 一致）；字段一律 snake_case。
 */
import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";

// ============================================================
// 接口地址
// ============================================================

/** 剧本 AI 生成接口地址（routers/story 的 session/generation/sediment 路由） */
export const STORY_AI_URL = {
  /** 会话列表 / 创建 */
  sessions: (projectId: string) => `/story/projects/${projectId}/sessions`,
  /** 最近活跃会话（抽屉默认打开目标） */
  latestSession: (projectId: string) => `/story/projects/${projectId}/sessions/latest`,
  /** 会话详情 / 删除 */
  sessionById: (sessionId: string) => `/story/sessions/${sessionId}`,
  /** 会话消息历史 */
  sessionMessages: (sessionId: string) => `/story/sessions/${sessionId}/messages`,
  /** 视频风格注册表枚举 */
  styles: "/story/styles",
  /** SSE 流式剧本生成 */
  generate: (sessionId: string) => `/story/sessions/${sessionId}/generate`,
  /** 停止生成 */
  stop: (sessionId: string) => `/story/sessions/${sessionId}/stop`,
  /** 生成任务列表 / 详情 */
  taskById: (taskId: string) => `/story/generation-tasks/${taskId}`,
  projectTasks: (projectId: string) => `/story/projects/${projectId}/generation-tasks`,
  /** 立绘生成 / 角色卡编辑 / 剧本与角色沉淀 */
  generateArt: (messageId: string) => `/story/messages/${messageId}/generate-art`,
  editCard: (messageId: string) => `/story/messages/${messageId}/card`,
  saveScript: (messageId: string) => `/story/messages/${messageId}/save-script`,
} as const;

/** 角色沉淀地址（独立导出，避免对象字面量自引用） */
export const STORY_SAVE_CHARACTER_URL = (messageId: string) =>
  `/story/messages/${messageId}/save-character`;

// ============================================================
// 类型定义
// ============================================================

/** 生成会话 VO（后端 StorySession.to_dict） */
export interface StorySessionVO {
  id: string;
  project_id: string;
  title: string | null;
  type: string;
  message_count: number;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

/** 消息产物类型 */
export type StoryMessageKind = "general" | "script" | "character" | "art" | "keyframe";

/** 会话消息 VO（后端 StoryMessage.to_dict） */
export interface StoryMessageVO {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  kind: StoryMessageKind;
  content: string;
  image_file: string | null;
  prompt: string | null;
  params: Record<string, unknown> | null;
  sequence: number;
  status: "generating" | "done" | "stopped" | "failed";
  error: string | null;
  created_at: string;
}

/** 生成会话内嵌于角色卡消息的结构化卡片数据（双轨输出契约） */
export interface StoryCharacterCard {
  name: string;
  role_type: string | null;
  profile: Record<string, unknown>;
  visual_profile: Record<string, unknown>;
  appearance_prompt: string | null;
  art_prompt: string | null;
  negative_prompt: string | null;
}

/** 视频风格（风格注册表条目） */
export interface StoryStyleVO {
  key: string;
  name: string;
  description: string;
  aspect_ratios: string[];
}

/** 生成任务 VO（后端 StoryGenerationTask.to_dict） */
export interface StoryGenerationTaskVO {
  id: string;
  project_id: string;
  session_id: string | null;
  task_type: string;
  status: string;
  progress: number;
  result_image_file: string | null;
  error_code: string | null;
  error_message: string | null;
  params: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  result_text?: string;
}

/** 剧本生成请求体 */
export interface StoryGeneratePayload {
  idea: string;
  style_key: string;
  aspect_ratio?: string | null;
  episodes?: number | null;
  tone?: string | null;
}

/** done 帧数据（含角色卡与降级信息） */
export interface StoryDonePayload {
  session_id: string;
  message_id: string;
  status: "done" | "stopped" | "failed";
  cards?: StoryCharacterCard[];
  cards_ok?: boolean;
  cards_error?: string | null;
  params?: Record<string, unknown>;
  duration_ms?: number;
}

/** 流式事件（已按事件类型解析 data） */
export interface StoryStreamEvent {
  event: "think" | "answer" | "done" | "error";
  text?: string;
  delta?: string;
  session_id?: string;
  done?: StoryDonePayload;
  msg?: string;
}

// ============================================================
// SSE 解析（对齐 aichat 的 fetch-stream 模式）
// ============================================================

const API_BASE_URL: string = import.meta.env.VITE_APP_BASE_API || "";

/** 解析单个 SSE 块为类型化事件；未知事件安全忽略 */
function parseSSEBlock(block: string): StoryStreamEvent | null {
  let eventName = "";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!eventName) return null;
  let data: unknown = null;
  try {
    data = dataLines.length ? JSON.parse(dataLines.join("\n")) : null;
  } catch {
    data = null;
  }
  if (eventName === "think") {
    const payload = (data ?? {}) as { text?: string; session_id?: string };
    return { event: "think", text: payload.text ?? "", session_id: payload.session_id };
  }
  if (eventName === "answer") {
    const payload = (data ?? {}) as { delta?: string };
    return { event: "answer", delta: payload.delta ?? "" };
  }
  if (eventName === "done") {
    return { event: "done", done: data as StoryDonePayload };
  }
  if (eventName === "error") {
    const payload = (data ?? {}) as { msg?: string };
    return { event: "error", msg: payload.msg ?? "剧本生成失败，请稍后重试" };
  }
  return null;
}

// ============================================================
// API 封装
// ============================================================

export const storyAiApi = {
  // ---------- 会话 ----------

  /** 分页列出项目下会话，最近活跃倒序 */
  listSessions(projectId: string, page = 1, size = 20) {
    return request.get<PageResult<StorySessionVO>, ApiResult<PageResult<StorySessionVO>>>(
      STORY_AI_URL.sessions(projectId),
      { params: { page, size } }
    );
  },

  /** 项目最近活跃会话（无会话时 data 为 null） */
  latestSession(projectId: string) {
    return request.get<StorySessionVO | null, ApiResult<StorySessionVO | null>>(
      STORY_AI_URL.latestSession(projectId)
    );
  },

  /** 创建生成会话 */
  createSession(projectId: string, title?: string, type = "general") {
    return request.post<StorySessionVO, ApiResult<StorySessionVO>>(
      STORY_AI_URL.sessions(projectId),
      { title, type }
    );
  },

  /** 删除会话（未沉淀结果随之丢弃） */
  removeSession(sessionId: string) {
    return request.delete<null, ApiResult<null>>(STORY_AI_URL.sessionById(sessionId));
  },

  /** 会话消息历史（sequence 升序分页） */
  messages(sessionId: string, page = 1, size = 50) {
    return request.get<PageResult<StoryMessageVO>, ApiResult<PageResult<StoryMessageVO>>>(
      STORY_AI_URL.sessionMessages(sessionId),
      { params: { page, size } }
    );
  },

  // ---------- 生成 ----------

  /** 视频风格注册表枚举 */
  styles() {
    return request.get<StoryStyleVO[], ApiResult<StoryStyleVO[]>>(STORY_AI_URL.styles);
  },

  /**
   * 流式剧本生成（SSE）。
   * 业务拒绝（互斥/未注册风格）返回 JSON 统一响应，解析 {code,msg} 并抛出。
   * @returns 中止请求的函数
   */
  async generate(
    sessionId: string,
    data: StoryGeneratePayload,
    onMessage: (event: StoryStreamEvent) => void,
    onError?: (error: Error) => void,
    onComplete?: () => void
  ): Promise<() => void> {
    const { getToken } = await import("@/utils/auth");
    const controller = new AbortController();
    try {
      const response = await fetch(`${API_BASE_URL}${STORY_AI_URL.generate(sessionId)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken()}`,
          Accept: "text/event-stream",
        },
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      if (response.status === 401) {
        window.location.replace("/login");
        throw new Error("登录凭证已失效");
      }
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.includes("text/event-stream")) {
        const result = (await response.json().catch(() => null)) as ApiResult | null;
        throw new Error(result?.msg || `HTTP error! status: ${response.status}`);
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error("无法获取响应流");
      const decoder = new TextDecoder();
      let buffer = "";
      (async () => {
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) {
              const remaining = buffer.trim();
              if (remaining) {
                const event = parseSSEBlock(remaining);
                if (event) onMessage(event);
              }
              onComplete?.();
              break;
            }
            buffer += decoder.decode(value, { stream: true });
            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop() ?? "";
            for (const block of blocks) {
              const event = parseSSEBlock(block);
              if (event) onMessage(event);
            }
          }
        } catch (err: unknown) {
          if ((err as Error).name !== "AbortError") onError?.(err as Error);
        }
      })();
    } catch (error: unknown) {
      if ((error as Error).name !== "AbortError") onError?.(error as Error);
    }
    return () => controller.abort();
  },

  /** 停止生成（无在途任务幂等成功） */
  stop(sessionId: string) {
    return request.post<{ cancelled: boolean }, ApiResult<{ cancelled: boolean }>>(
      STORY_AI_URL.stop(sessionId)
    );
  },

  /** 生成任务详情（with_result_text 携带剧本全文） */
  task(taskId: string, withResultText = false) {
    return request.get<StoryGenerationTaskVO, ApiResult<StoryGenerationTaskVO>>(
      STORY_AI_URL.taskById(taskId),
      { params: { with_result_text: withResultText } }
    );
  },

  // ---------- 立绘与沉淀 ----------

  /** 从角色卡发起内部立绘生成（返回任务记录，前端轮询） */
  generateArt(messageId: string, size?: string) {
    return request.post<StoryGenerationTaskVO, ApiResult<StoryGenerationTaskVO>>(
      STORY_AI_URL.generateArt(messageId),
      { size }
    );
  },

  /** 编辑角色卡字段（沉淀前修订） */
  editCard(
    messageId: string,
    payload: Partial<Pick<StoryCharacterCard, "name" | "role_type" | "profile" | "visual_profile" | "appearance_prompt" | "art_prompt" | "negative_prompt">>
  ) {
    return request.put<StoryMessageVO, ApiResult<StoryMessageVO>>(
      STORY_AI_URL.editCard(messageId),
      payload
    );
  },

  /** 剧本卡存为项目剧本新版本（source='ai'，重复沉淀产生新版本） */
  saveScript(messageId: string, title?: string, setCurrent = false) {
    return request.post<Record<string, unknown>, ApiResult<Record<string, unknown>>>(
      STORY_AI_URL.saveScript(messageId),
      { title, set_current: setCurrent }
    );
  },

  /**
   * 角色卡存入角色库（单事务：建角色/并入 + 立绘收编 + 自动出演登记）。
   * 同名角色由调用方先行提示，mode='merge' 时须提供 character_id。
   */
  saveCharacter(messageId: string, mode: "new" | "merge", characterId?: string) {
    return request.post<
      { mode: string; character: Record<string, unknown>; saved_art_count: number; casting_added: boolean },
      ApiResult<{ mode: string; character: Record<string, unknown>; saved_art_count: number; casting_added: boolean }>
    >(STORY_SAVE_CHARACTER_URL(messageId), { mode, character_id: characterId });
  },
}
