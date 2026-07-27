import service from "@/utils/request";
import { aiUrl } from "./index";

// ============================================================
// 类型定义
// ============================================================

/** AI问答请求参数 */
export interface ChatserviceDTO {
  /** 用户问题内容 */
  question: string;
  /** 知识库ID列表，限定检索范围（可选） */
  kbIds?: number[];
  /** 标签ID列表，限定检索范围（可选） */
  tagIds?: number[];
  /** 返回相似文档数量（可选，默认10） */
  topK?: number;
  /** 相似度阈值（可选，默认0.5） */
  similarityThreshold?: number;
  /** 是否返回思考过程（可选，默认false） */
  showThinking?: boolean;
  /** 是否返回引用来源（可选，默认true） */
  showSources?: boolean;
  /** 会话ID，用于多轮对话（可选，不传自动生成） */
  sessionId?: string;
  /** 是否清除会话历史（可选，默认false） */
  clearHistory?: boolean;
  /** 最大历史消息数（可选，默认20） */
  maxHistory?: number;
}

/** 引用来源信息 */
export interface ChatSource {
  /** 来源序号，对应回答中的 [index] */
  index: number;
  /** 文档ID */
  documentId: number;
  /** 文档名称 */
  documentName: string;
  /** 知识库ID */
  kbId: number;
  /** 知识库名称 */
  kbName: string;
  /** 相似度分数 */
  similarityScore: number;
  /** 引用内容 */
  content: string;
  /** 引用内容片段（兼容旧字段） */
  contentSnippet?: string;
}

/** AI问答响应结果 */
export interface ChatResponseVO {
  /** AI回答内容 */
  answer: string;
  /** 思考过程（仅showThinking=true时返回） */
  thinking?: string;
  /** 引用来源列表 */
  sources?: ChatSource[];
  /** 是否有知识库检索结果 */
  hasKbResult: boolean;
  /** 会话ID，用于后续多轮对话 */
  sessionId: string;
}

/** 会话信息 */
export interface SessionVO {
  /** 会话ID */
  sessionId: string;
  /** 用户ID */
  userId: string | number;
  /** 会话标题 */
  title?: string;
  /** 消息数量 */
  messageCount: number;
  /** 会话摘要内容 */
  summary?: string | null;
  /** 创建时间 */
  createTime: string;
  /** 最后访问时间 */
  lastAccessTime: string;
}

/** 会话详情 */
export interface SessionDetailVO extends SessionVO {
  /** 会话摘要内容 */
  summary: string;
}

/** 消息历史记录 */
export interface SessionMessageVO {
  /** 消息ID */
  id: number;
  /** 消息类型：USER/ASSISTANT */
  messageType: "USER" | "ASSISTANT";
  /** 消息内容 */
  content: string;
  /** 引用来源列表 */
  sources?: ChatSource[];
  /** 消息序号 */
  sequence: number;
  /** 创建时间 */
  createTime: string;
}

/** 会话统计信息 */
export interface SessionStatsVO {
  /** 总会话数 */
  totalSessions: number;
  /** 总消息数 */
  totalMessages: number;
}

/** 通用操作响应 */
export interface CommonMsgVO {
  /** 提示消息 */
  msg: string;
}

/** 聊天流式事件 */
export interface ChatStreamEvent {
  /** SSE event 名称 */
  event: "think" | "answer" | "message" | "sources" | "done" | "reset" | string;
  /** 从 data 中解析出的文本 */
  text: string;
  /** 原始 data 内容 */
  rawData: string;
  /** 后端事件时间戳 */
  timestamp?: number;
  /** 后端会话ID */
  sessionId?: string;
  /** 解析后的 data */
  data?: unknown;
}

export type ChatStreamEventHandler = (event: ChatStreamEvent) => void;

// ============================================================
// SSE 辅助函数
// ============================================================

/** API 基础地址（与 service.ts 保持一致） */
const API_BASE_URL = import.meta.env.VITE_API_URL || "/prod-api";

function parseStreamData(rawData: string): Omit<ChatStreamEvent, "event" | "rawData"> {
  if (!rawData) return { text: "" };

  try {
    const data = JSON.parse(rawData);
    if (typeof data === "string") return { text: data, data };
    if (data && typeof data === "object") {
      const payload = data as Record<string, unknown>;
      return {
        text: String(payload.text ?? payload.answer ?? payload.content ?? payload.delta ?? ""),
        timestamp: typeof payload.timestamp === "number" ? payload.timestamp : undefined,
        sessionId: typeof payload.sessionId === "string" ? payload.sessionId : undefined,
        data,
      };
    }
    return { text: String(data), data };
  } catch {
    return { text: rawData };
  }
}

function parseSSEBlock(block: string): ChatStreamEvent | null {
  const lines = block.split(/\r?\n/);
  let eventName = "message";
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

  if (!eventName && !dataLines.length) return null;

  const rawData = dataLines.join("\n");
  if (rawData === "[DONE]") {
    return { event: "done", text: "", rawData };
  }

  return {
    event: eventName,
    rawData,
    ...parseStreamData(rawData),
  };
}

/**
 * 发起 SSE 流式请求
 * @param url 请求路径
 * @param data 请求体数据
 * @param onMessage 收到流式事件时的回调
 * @param onError 发生错误时的回调
 * @param onComplete 流结束时的回调
 * @returns 中止请求的函数
 */
async function serviceSSE(
  url: string,
  data: ChatserviceDTO,
  onMessage: ChatStreamEventHandler,
  onError?: (error: Error) => void,
  onComplete?: () => void
): Promise<() => void> {
  const { useUserStore } = await import("@/stores/userStore");
  const userStore = useUserStore();

  const token = userStore.token;
  if (!token) {
    window.location.replace("/login");
    throw new Error("令牌不能为空");
  }

  const controller = new AbortController();

  try {
    const response = await fetch(`${API_BASE_URL}${url}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token.trim()}`,
        Accept: "text/event-stream",
      },
      body: JSON.stringify(data),
      signal: controller.signal,
    });

    if (response.status === 401) {
      // 登录凭证失效：走 store 登出流程清除本地状态并跳转登录页
      await userStore.logout();
      window.location.replace("/login");
      throw new Error("登录凭证已失效");
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
   * 流式问答（SSE），通过请求体中的 showThinking 参数控制是否返回思考过程
   * @param data 问答请求参数
   * @param onMessage 收到流式事件时的回调
   * @param onError 发生错误时的回调
   * @param onComplete 流结束时的回调
   * @returns 中止请求的函数
   */
  chatStream(
    data: ChatserviceDTO,
    onMessage: ChatStreamEventHandler,
    onError?: (error: Error) => void,
    onComplete?: () => void
  ): Promise<() => void> {
    return serviceSSE(aiUrl.chat.stream, data, onMessage, onError, onComplete);
  },

  /**
   * 停止生成
   * @returns 停止结果
   */
  stopGeneration(sessionId: string) {
    return service(`${aiUrl.chat.stop}/${sessionId}`, { method: "POST" });
  },
};

// ============================================================
// AI 会话 API
// ============================================================

export const AiSessionApi = {
  /**
   * 获取会话列表
   * @returns 当前用户的所有会话列表
   */
  getSessionList(): Promise<SessionVO[]> {
    return service(aiUrl.session.list, {
      method: "GET",
    });
  },

  /**
   * 获取会话消息历史
   * @param sessionId 会话ID
   * @returns 指定会话的所有消息历史
   */
  getSessionMessages(sessionId: string): Promise<SessionMessageVO[]> {
    return service(`${aiUrl.session.base}/${sessionId}/messages`, {
      method: "GET",
    });
  },

  /**
   * 获取会话详情
   * @param sessionId 会话ID
   * @returns 会话详情（包含摘要信息）
   */
  getSessionDetail(sessionId: string): Promise<SessionDetailVO> {
    return service(`${aiUrl.session.base}/${sessionId}`, {
      method: "GET",
    });
  },

  /**
   * 删除指定会话
   * @param sessionId 会话ID
   * @returns 删除结果
   */
  deleteSession(sessionId: string): Promise<CommonMsgVO> {
    return service(`${aiUrl.session.base}/${sessionId}`, {
      method: "DELETE",
    });
  },

  /**
   * 删除所有会话
   * @returns 删除结果
   */
  deleteAllSessions(): Promise<CommonMsgVO> {
    return service(aiUrl.session.all, {
      method: "DELETE",
    });
  },

  /**
   * 获取会话统计
   * @returns 当前用户的会话统计信息
   */
  getSessionStats(): Promise<SessionStatsVO> {
    return service(aiUrl.session.stats, {
      method: "GET",
    });
  },

  /**
   * 创建会话
   * @returns 创建结果
   */
  createSession(): Promise<SessionVO> {
    return service(aiUrl.session.create, {
      method: "POST",
    });
  },
};
