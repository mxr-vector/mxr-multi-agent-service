/**
 * RAG 模块后端接口地址维护中心。
 *
 * request 实例的 baseURL 为 VITE_APP_BASE_API（如 /dev-api），经 Vite 代理转发时会剥离该前缀，
 * 因此这里的路径需带上后端父路由前缀 BASE（对应服务端 ENV.base_url = /multi-agent-base）。
 *
 * 所有 RAG 功能函数统一从各子模块导入这里维护的 URL，避免地址散落各处。
 */

/** 后端父路由前缀（对应服务端 ENV.base_url） */
const BASE = "/multi-agent-base";

/** RAG 分类管理接口地址 */
export const CATEGORY_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/rag/categories`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/rag/categories/${id}`,
} as const;

/** RAG 知识库管理接口地址 */
export const KNOWLEDGE_BASE_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/rag/knowledge-base`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/rag/knowledge-base/${id}`,
} as const;

/** RAG 文档管理接口地址 */
export const DOCUMENT_URL = {
  /** 列表 */
  root: `${BASE}/rag/document`,
  /** 上传（解析 + 两级切块 + 落库） */
  upload: `${BASE}/rag/document/upload`,
  /** 详情 / 更新 */
  byId: (id: string) => `${BASE}/rag/document/${id}`,
  /** 单独触发向量化 */
  vectorize: (id: string) => `${BASE}/rag/document/${id}/vectorize`,
} as const;

/** RAG 文档分块管理接口地址 */
export const CHUNK_URL = {
  /** 列表 */
  root: `${BASE}/rag/chunks`,
  /** 详情 */
  byId: (id: string) => `${BASE}/rag/chunks/${id}`,
} as const;

// 统一出口：业务侧可直接从 "@/api/rag" 导入功能函数与类型
export * from "./categories";
export * from "./knowledgeBase";
export * from "./document";
export * from "./chunks";
