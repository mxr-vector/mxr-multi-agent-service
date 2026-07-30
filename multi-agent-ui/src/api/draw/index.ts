/**
 * 绘图模块后端接口地址维护中心。
 *
 * request 实例的 baseURL 为 VITE_APP_BASE_API（如 /dev-api），经 Vite 代理转发时会剥离该前缀，
 * 因此这里的路径直接对应服务端 routers/draw 下的路由前缀。
 */

/** 后端绘图路由前缀（routers/draw） */
const BASE = "/draw";

/** 流式生成与上传接口地址 */
export const DRAW_URL = {
  /** SSE 流式生成 */
  completions: `${BASE}/completions`,
  /** 停止生成 */
  stop: (sessionId: string) => `${BASE}/stop/${sessionId}`,
  /** 图片上传（重绘素材） */
  upload: `${BASE}/upload`,
} as const;

/** 绘图会话与版本接口地址 */
export const DRAW_SESSION_URL = {
  /** 会话列表（GET，分页） */
  root: `${BASE}/sessions`,
  /** 会话删除 */
  byId: (sessionId: string) => `${BASE}/sessions/${sessionId}`,
  /** 会话消息历史（分页） */
  messages: (sessionId: string) => `${BASE}/sessions/${sessionId}/messages`,
  /** 会话图表版本链 */
  versions: (sessionId: string) => `${BASE}/sessions/${sessionId}/versions`,
} as const;

export const DRAW_VERSION_URL = {
  /** 版本保存（POST，multipart）*/
  root: `${BASE}/versions`,
  /** 版本详情（携带 drawio_xml） */
  byId: (versionId: string) => `${BASE}/versions/${versionId}`,
} as const;

// 统一出口：业务侧可直接从 "@/api/draw" 导入 API 对象与类型
export * from "./draw";
