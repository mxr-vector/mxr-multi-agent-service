import request, { type ApiResult } from "@/utils/request";
import { getToken } from "@/utils/auth";
import type { PageResult } from "@/api/rag";
import { CHAT_URL, SESSION_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/chat 契约，字段一律 snake_case）
// ============================================================

/** 流式问答请求体（POST /chat/completions） */
export interface ChatCompletionPayload {
  /** 用户问题内容 */
  question: string;
  /** 会话ID（hex 无连字符）；缺省时后端自动建会话并在首个 think 帧回传 */
  session_id?: string;
  /** 消息级检索范围（知识库 hex id 列表）；缺省按当前用户可见范围解析 */
  kb_ids?: string[];
  /** 联网搜索开关（后端暂未实现，固定透传） */
  use_web_search?: boolean;
  /** 思考强度（词典 reasoning_effort 维护取值）；缺省用后端默认 */
  reasoning_effort?: string;
}

/** 引用来源（后端 sources 富化结构，见 service/rag/chat.py::_enrich_sources） */
export interface ChatSource {
  /** 引用序号（1 起），对应回答正文中的 [n] 角标 */
  index: number;
  /** 引用内容片段 */
  text: string;
  /** 原始来源标识（文件名等） */
  source: string;
  /** rerank 得分 */
  score: number | null;
  /** 知识库ID（hex） */
  knowledge_base_id: string | null;
  /** 章节标题 */
  chapter_title: string | null;
  /** 文档ID（hex） */
  document_id: string | null;
  /** 分块ID */
  chunk_id: string | null;
  /** 起始页码 */
  page_start: number | null;
  /** 结束页码 */
  page_end: number | null;
  /** 文档名（实体已删时为 null） */
  document_name: string | null;
  /** 知识库名（实体已删时为 null） */
  kb_name: string | null;
  /** 相似度百分比（0-100 整数） */
  similarity_percent: number | null;
  /** 相似度分级 high/medium/low */
  similarity_level: string | null;
}

/** 会话信息（对应后端 ChatSession.to_dict） */
export interface ChatSessionVO {
  /** 会话ID（hex 无连字符） */
  id: string;
  /** 属主用户ID */
  user_id: string;
  /** 会话标题（首轮问答后由摘要任务回填） */
  title: string;
  /** 消息数量 */
  message_count: number;
  /** 最后消息时间 */
  last_message_at: string | null;
  /** 状态 active/deleted */
  status: string;
  /** 创建时间 */
  created_at: string;
  /** 更新时间 */
  updated_at: string;
}

/** 消息终态生命周期 */
export type ChatMessageStatus = "generating" | "done" | "stopped" | "failed";

/** 会话消息（对应后端 ChatMessage.to_dict） */
export interface ChatMessageVO {
  /** 消息ID（hex） */
  id: string;
  /** 会话ID（hex） */
  session_id: string;
  /** 消息角色 */
  role: "user" | "assistant";
  /** 消息内容 */
  content: string;
  /** 思考过程（仅 assistant 消息） */
  thinking: string | null;
  /** 引用来源列表 */
  sources: ChatSource[];
  /** 消息级检索范围快照（仅 user 消息） */
  kb_ids: string[] | null;
  /** 推理复杂度指标（仅 assistant 消息） */
  metrics: Record<string, unknown> | null;
  /** 会话内单调序号 */
  sequence: number;
  /** 消息状态 */
  status: ChatMessageStatus;
  /** 失败原因 */
  error: string | null;
  /** 创建时间 */
  created_at: string;
}

/** SSE 事件名（对应后端 SseEvent 枚举） */
export type ChatSseEventName = "think" | "answer" | "sources" | "done" | "error";

/** done 帧数据 */
export interface ChatDonePayload {
  session_id: string;
  message_id: string;
  status: ChatMessageStatus;
  metrics: Record<string, unknown>;
}

/** 聊天流式事件（已按事件类型解析 data） */
export interface ChatStreamEvent {
  /** SSE event 名称 */
  event: ChatSseEventName;
  /** think 帧的进展文本 */
  text?: string;
  /** answer 帧的答案增量 */
  delta?: string;
  /** think/done 帧携带的会话ID */
  session_id?: string;
  /** sources 帧的来源列表 */
  sources?: ChatSource[];
  /** done 帧数据 */
  done?: ChatDonePayload;
  /** error 帧的错误信息 */
  msg?: string;
}

export type ChatStreamEventHandler = (event: ChatStreamEvent) => void;

// ============================================================
// SSE 辅助函数
// ============================================================

/** API 基础地址（与 utils/request.ts 的 baseURL 保持一致） */
const API_BASE_URL: string = import.meta.env.VITE_APP_BASE_API || "";

/** 把 SSE 帧的 event + data(JSON) 解析为类型化事件 */
function parseSSEBlock(block: string): ChatStreamEvent | null {
  const lines = block.split(/\r?\n/);
  let eventName = "";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (!eventName) return null;

  let data: unknown = null;
  try {
    data = dataLines.length ? JSON.parse(dataLines.join("\n")) : null;
  } catch {
    data = null;
  }

  switch (eventName as ChatSseEventName) {
    case "think": {
      const payload = (data ?? {}) as { text?: string; session_id?: string };
      return { event: "think", text: payload.text ?? "", session_id: payload.session_id };
    }
    case "answer": {
      const payload = (data ?? {}) as { delta?: string };
      return { event: "answer", delta: payload.delta ?? "" };
    }
    case "sources":
      return { event: "sources", sources: Array.isArray(data) ? (data as ChatSource[]) : [] };
    case "done": {
      const payload = data as ChatDonePayload;
      return { event: "done", done: payload, session_id: payload?.session_id };
    }
    case "error": {
      const payload = (data ?? {}) as { msg?: string };
      return { event: "error", msg: payload.msg ?? "回答生成失败，请稍后重试" };
    }
    default:
      return null;
  }
}

/**
 * 发起 SSE 流式请求。
 *
 * 后端在进入流之前的业务拒绝（如同会话生成互斥）会返回 JSON 统一响应
 * 而非 event-stream，此时解析 {code, msg} 并抛出 msg。
 *
 * @returns 中止请求的函数
 */
async function requestSSE(
  url: string,
  data: ChatCompletionPayload,
  onMessage: ChatStreamEventHandler,
  onError?: (error: Error) => void,
  onComplete?: () => void
): Promise<() => void> {
  const controller = new AbortController();

  try {
    const response = await fetch(`${API_BASE_URL}${url}`, {
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

    // 非流式响应：业务异常走统一响应结构 {code, msg}
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("text/event-stream")) {
      const result = (await response.json().catch(() => null)) as ApiResult | null;
      throw new Error(result?.msg || `HTTP error! status: ${response.status}`);
    }

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("无法获取响应流");
    }

    const decoder = new TextDecoder();
    let sseBuffer = "";

    (async () => {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            const remaining = sseBuffer.trim();
            if (remaining) {
              const event = parseSSEBlock(remaining);
              if (event) onMessage(event);
            }
            onComplete?.();
            break;
          }

          sseBuffer += decoder.decode(value, { stream: true });
          const blocks = sseBuffer.split(/\r?\n\r?\n/);
          sseBuffer = blocks.pop() ?? "";

          for (const block of blocks) {
            const event = parseSSEBlock(block);
            if (event) onMessage(event);
          }
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          onError?.(err);
        }
      }
    })();
  } catch (error: any) {
    if (error.name !== "AbortError") {
      onError?.(error);
    }
  }

  return () => controller.abort();
}

// ============================================================
// AI 问答 API
// ============================================================

export const AiChatApi = {
  /**
   * 流式问答（SSE）
   * @param data 问答请求参数
   * @param onMessage 收到流式事件时的回调
   * @param onError 发生错误时的回调
   * @param onComplete 流结束时的回调
   * @returns 中止请求的函数
   */
  chatStream(
    data: ChatCompletionPayload,
    onMessage: ChatStreamEventHandler,
    onError?: (error: Error) => void,
    onComplete?: () => void
  ): Promise<() => void> {
    return requestSSE(CHAT_URL.completions, data, onMessage, onError, onComplete);
  },

  /** 停止生成：取消该会话在途生成任务（无在途任务幂等成功） */
  stop(sessionId: string) {
    return request.post<{ cancelled: boolean }, ApiResult<{ cancelled: boolean }>>(
      CHAT_URL.stop(sessionId)
    );
  },
};

// ============================================================
// AI 问答会话 API
// ============================================================

export const AiSessionApi = {
  /** 分页列出本人会话，按最后消息时间倒序 */
  list(page = 1, size = 20) {
    return request.get<PageResult<ChatSessionVO>, ApiResult<PageResult<ChatSessionVO>>>(
      SESSION_URL.root,
      { params: { page, size } }
    );
  },

  /** 会话消息历史，按 sequence 升序分页 */
  messages(sessionId: string, page = 1, size = 50) {
    return request.get<PageResult<ChatMessageVO>, ApiResult<PageResult<ChatMessageVO>>>(
      SESSION_URL.messages(sessionId),
      { params: { page, size } }
    );
  },

  /** 删除指定会话（软删 + 清理 checkpoint） */
  remove(sessionId: string) {
    return request.delete<null, ApiResult<null>>(SESSION_URL.byId(sessionId));
  },

  /** 清空本人全部会话 */
  removeAll() {
    return request.delete<{ deleted: number }, ApiResult<{ deleted: number }>>(SESSION_URL.root);
  },
};
