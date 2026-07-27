/**
 * RAG 模块后端接口地址维护中心。
 *
 * request 实例的 baseURL 为 VITE_APP_BASE_API（如 /dev-api），经 Vite 代理转发时会剥离该前缀，
 * 因此这里的路径需带上后端父路由前缀 BASE（对应服务端 ENV.base_url = /multi-agent-base）。
 *
 * 所有 RAG 功能函数统一从各子模块导入这里维护的 URL，避免地址散落各处。
 */

/** 后端父路由前缀（对应服务端 ENV.base_url） */
const BASE = "/rag";

/**
 * 统一分页结果契约（对应后端 utils/page.py::PageResult）。
 *
 * items 为当前页数据，total 为过滤后的总量，pages 为总页数；
 * 作为统一响应 ApiResult 的 data 载荷返回。
 */
export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

/** RAG 文件夹管理接口地址 */
export const FOLDER_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/folders`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/folders/${id}`,
} as const;

/** RAG 知识库管理接口地址 */
export const KNOWLEDGE_BASE_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/knowledge-base`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/knowledge-base/${id}`,
} as const;

/** RAG 文档管理接口地址 */
export const DOCUMENT_URL = {
  /** 列表 */
  root: `${BASE}/document`,
  /** 上传（解析 + 两级切块 + 落库） */
  upload: `${BASE}/document/upload`,
  /** 详情 / 更新 */
  byId: (id: string) => `${BASE}/document/${id}`,
  /** 单独触发向量化 */
  vectorize: (id: string) => `${BASE}/document/${id}/vectorize`,
  /** 批量查询向量化状态（轮询） */
  status: `${BASE}/document/status`,
} as const;

/** RAG 文档分块管理接口地址 */
export const CHUNK_URL = {
  /** 列表 */
  root: `${BASE}/chunks`,
  /** 详情 */
  byId: (id: string) => `${BASE}/chunks/${id}`,
} as const;

/** RAG 统计接口地址 */
export const STATS_URL = {
  /** 全局聚合概览 */
  root: `${BASE}/stats`,
} as const;

// 统一出口：业务侧可直接从 "@/api/rag" 导入 xxApi 对象（folderApi/knowledgeBaseApi/documentApi/chunkApi/statsApi）与类型
export * from "./folders";
export * from "./knowledgeBase";
export * from "./document";
export * from "./chunks";
export * from "./stats";
