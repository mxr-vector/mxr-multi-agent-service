import request, { type ApiResult } from "@/utils/request";
import { getToken } from "@/utils/auth";
import type { PageResult } from "@/api/rag";
import { DRAW_URL, DRAW_SESSION_URL, DRAW_VERSION_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/draw 契约，字段一律 snake_case）
// ============================================================

/** 流式生成请求体（POST /draw/completions） */
export interface DrawCompletionPayload {
  /** 问题描述（与 image_file 至少其一非空） */
  question: string;
  /** 会话ID（hex 无连字符）；缺省时后端自动建会话并在首个 think 帧回传 */
  session_id?: string;
  /** 上传端点返回的图片相对路径（如 draw/upload/xxx.png） */
  image_file?: string;
  /** 多轮改图基线版本 id：模型基于其 Mermaid 源修改，新版本 parent_id 指向它 */
  base_version_id?: string;
}

/** 绘图消息状态（对应后端 ChatMessageStatus） */
export type DrawMessageStatus = "generating" | "done" | "stopped" | "failed";

/** 绘图会话 VO */
export interface DrawSessionVO {
  id: string;
  user_id: string;
  title: string;
  message_count: number;
  last_message_at: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/** 绘图消息 VO */
export interface DrawMessageVO {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  image_file: string | null;
  sequence: number;
  status: DrawMessageStatus;
  error: string | null;
  created_at: string;
}

/** 图表版本 VO（列表不携带 drawio_xml，详情接口携带） */
export interface DrawVersionVO {
  id: string;
  session_id: string;
  message_id: string | null;
  parent_id: string | null;
  source_type: "ai" | "user";
  mermaid_source: string | null;
  preview_file: string | null;
  created_at: string;
  /** 仅版本详情接口返回 */
  drawio_xml?: string | null;
}

/** SSE 事件名（对应后端 SseEvent 枚举，绘图不产 sources 帧） */
export type DrawSseEventName = "think" | "answer" | "done" | "error";

/** done 帧数据 */
export interface DrawDonePayload {
  session_id: string;
  message_id: string;
  status: DrawMessageStatus;
  /** 生成成功时的 AI 版本 id；未提取到合法 Mermaid 为 null */
  version_id: string | null;
  /** 提取出的 Mermaid 源（与 version_id 同步存在） */
  mermaid_source: string | null;
  metrics: Record<string, unknown>;
}

/** 绘图流式事件（已按事件类型解析 data） */
export interface DrawStreamEvent {
  event: DrawSseEventName;
  /** think 帧的进展文本 */
  text?: string;
  /** answer 帧的答案增量 */
  delta?: string;
  /** think/done 帧携带的会话ID */
  session_id?: string;
  /** done 帧数据 */
  done?: DrawDonePayload;
  /** error 帧的错误信息 */
  msg?: string;
}

export type DrawStreamEventHandler = (event: DrawStreamEvent) => void;

// ============================================================
// SSE 辅助函数（与 api/aichat/ai.ts 同构：fetch + ReadableStream）
// ============================================================

/** API 基础地址（与 utils/request.ts 的 baseURL 保持一致） */
const API_BASE_URL: string = import.meta.env.VITE_APP_BASE_API || "";

/** 把 SSE 帧的 event + data(JSON) 解析为类型化事件 */
function parseSSEBlock(block: string): DrawStreamEvent | null {
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

  switch (eventName as DrawSseEventName) {
    case "think": {
      const payload = (data ?? {}) as { text?: string; session_id?: string };
      return { event: "think", text: payload.text ?? "", session_id: payload.session_id };
    }
    case "answer": {
      const payload = (data ?? {}) as { delta?: string };
      return { event: "answer", delta: payload.delta ?? "" };
    }
    case "done": {
      const payload = data as DrawDonePayload;
      return { event: "done", done: payload, session_id: payload?.session_id };
    }
    case "error": {
      const payload = (data ?? {}) as { msg?: string };
      return { event: "error", msg: payload.msg ?? "图表生成失败，请稍后重试" };
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
  data: DrawCompletionPayload,
  onMessage: DrawStreamEventHandler,
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
// 绘图生成 API
// ============================================================

export const DrawChatApi = {
  /**
   * 流式生成（SSE）
   * @param data 生成请求参数
   * @param onMessage 收到流式事件时的回调
   * @param onError 发生错误时的回调
   * @param onComplete 流结束时的回调
   * @returns 中止请求的函数
   */
  chatStream(
    data: DrawCompletionPayload,
    onMessage: DrawStreamEventHandler,
    onError?: (error: Error) => void,
    onComplete?: () => void
  ): Promise<() => void> {
    return requestSSE(DRAW_URL.completions, data, onMessage, onError, onComplete);
  },

  /** 停止生成：取消该会话在途生成任务（无在途任务幂等成功） */
  stop(sessionId: string) {
    return request.post<{ cancelled: boolean }, ApiResult<{ cancelled: boolean }>>(
      DRAW_URL.stop(sessionId)
    );
  },

  /** 上传待重绘图片，返回 data/ 下相对路径（image_file） */
  upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    return request.post<{ image_file: string }, ApiResult<{ image_file: string }>>(
      DRAW_URL.upload,
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
  },
};

// ============================================================
// 绘图会话与版本 API
// ============================================================

export const DrawSessionApi = {
  /** 分页列出本人绘图会话，按最后消息时间倒序 */
  list(page = 1, size = 20) {
    return request.get<PageResult<DrawSessionVO>, ApiResult<PageResult<DrawSessionVO>>>(
      DRAW_SESSION_URL.root,
      { params: { page, size } }
    );
  },

  /** 会话消息历史，按 sequence 升序分页 */
  messages(sessionId: string, page = 1, size = 50) {
    return request.get<PageResult<DrawMessageVO>, ApiResult<PageResult<DrawMessageVO>>>(
      DRAW_SESSION_URL.messages(sessionId),
      { params: { page, size } }
    );
  },

  /** 会话图表版本链（创建时间升序，不携带 drawio_xml） */
  versions(sessionId: string) {
    return request.get<DrawVersionVO[], ApiResult<DrawVersionVO[]>>(
      DRAW_SESSION_URL.versions(sessionId)
    );
  },

  /** 删除指定会话（同事务清理消息与版本） */
  remove(sessionId: string) {
    return request.delete<null, ApiResult<null>>(DRAW_SESSION_URL.byId(sessionId));
  },
};

export const DrawVersionApi = {
  /** 版本详情（携带 drawio_xml，供 drawio 编辑器加载） */
  detail(versionId: string) {
    return request.get<DrawVersionVO, ApiResult<DrawVersionVO>>(DRAW_VERSION_URL.byId(versionId));
  },

  /**
   * drawio 编辑保存：append-only 新增 user 来源版本。
   * @param preview 编辑器导出的 xmlpng 预览（内嵌 XML 的 PNG），可缺省
   */
  save(params: {
    session_id: string;
    parent_id: string;
    drawio_xml: string;
    preview?: Blob | null;
  }) {
    const form = new FormData();
    form.append("session_id", params.session_id);
    form.append("parent_id", params.parent_id);
    form.append("drawio_xml", params.drawio_xml);
    if (params.preview != null) form.append("preview", params.preview, "preview.png");
    return request.post<DrawVersionVO, ApiResult<DrawVersionVO>>(DRAW_VERSION_URL.root, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
};
