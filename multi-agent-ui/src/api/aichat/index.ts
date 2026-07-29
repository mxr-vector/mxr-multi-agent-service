/**
 * AI 问答模块后端接口地址维护中心。
 *
 * request 实例的 baseURL 为 VITE_APP_BASE_API（如 /dev-api），经 Vite 代理转发时会剥离该前缀，
 * 因此这里的路径直接对应服务端 routers/chat 下的路由前缀。
 */

/** 后端 AI 问答路由前缀（routers/chat） */
const BASE = "/chat";

/** 流式问答接口地址 */
export const CHAT_URL = {
  /** SSE 流式问答 */
  completions: `${BASE}/completions`,
  /** 停止生成 */
  stop: (sessionId: string) => `${BASE}/stop/${sessionId}`,
} as const;

/** 问答会话管理接口地址 */
export const SESSION_URL = {
  /** 列表（GET，分页）/ 清空全部（DELETE） */
  root: `${BASE}/sessions`,
  /** 详情 / 删除 */
  byId: (sessionId: string) => `${BASE}/sessions/${sessionId}`,
  /** 会话消息历史（分页） */
  messages: (sessionId: string) => `${BASE}/sessions/${sessionId}/messages`,
} as const;

// 统一出口：业务侧可直接从 "@/api/aichat" 导入 API 对象与类型
export * from "./ai";
