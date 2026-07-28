import request, { type ApiResult } from "@/utils/request";
import { KNOWLEDGE_BASE_URL, type PageResult } from "./index";

/** 知识库实体（对应后端 rag_knowledge_bases.to_dict） */
export interface KnowledgeBase {
  id: string;
  dept_id: string;
  /** 归属部门名（列表接口由后端按当页 dept_id 批量聚合；未归属/无对应部门为 null） */
  dept_name?: string | null;
  name: string;
  description: string | null;
  icon: string | null;
  qdrant_collection: string;
  embedding_provider: string | null;
  embedding_model: string | null;
  embedding_dim: number | null;
  visibility: string;
  owner: string | null;
  document_count: number;
  total_chunk_count: number;
  status: string;
  created_at: string;
  updated_at: string;
}

/** 创建知识库请求体（仅元数据，不创建 Qdrant collection；qdrant_collection 由后端由 id 派生） */
export interface KnowledgeBaseCreatePayload {
  name: string;
  description?: string | null;
  icon?: string | null;
  embedding_provider?: string | null;
  embedding_model?: string | null;
  embedding_dim?: number | null;
  visibility?: string;
  owner?: string | null;
  /** 归属部门（仅 data_scope=all 生效，须为已存在部门）；缺省由服务端按用户上下文注入 */
  dept_id?: string | null;
}

/** 更新知识库请求体（仅可编辑元数据；dept_id/qdrant_collection/embedding_* 不可变） */
export interface KnowledgeBaseUpdatePayload {
  name?: string;
  description?: string | null;
  icon?: string | null;
  visibility?: string;
  owner?: string | null;
  status?: string;
}

/** 分页列出知识库参数 */
export interface KnowledgeBaseListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按名称/描述模糊搜索 */
  keyword?: string;
  /** 按部门集合过滤（IN 匹配，传部门子树 id 集合；仅 data_scope=all 生效） */
  dept_ids?: string[];
}

/** 知识库管理 API：统一通过 knowledgeBaseApi.xx() 调用 */
export const knowledgeBaseApi = {
  /** 创建知识库（dept_id 由服务端注入） */
  create(payload: KnowledgeBaseCreatePayload) {
    return request.post<KnowledgeBase, ApiResult<KnowledgeBase>>(KNOWLEDGE_BASE_URL.root, payload);
  },

  /** 分页列出知识库（排除软删除的），可选按关键词过滤 */
  list(params: KnowledgeBaseListParams = {}) {
    return request.get<PageResult<KnowledgeBase>, ApiResult<PageResult<KnowledgeBase>>>(
      KNOWLEDGE_BASE_URL.root,
      { params }
    );
  },

  /** 按 id 获取知识库 */
  get(kbId: string) {
    return request.get<KnowledgeBase, ApiResult<KnowledgeBase>>(KNOWLEDGE_BASE_URL.byId(kbId));
  },

  /** 仅元数据更新（含 status active↔archived）；不可变字段不受影响 */
  update(kbId: string, payload: KnowledgeBaseUpdatePayload) {
    return request.put<KnowledgeBase, ApiResult<KnowledgeBase>>(
      KNOWLEDGE_BASE_URL.byId(kbId),
      payload
    );
  },

  /** 软删除：置 status='deleted'，随后不再出现在列表中 */
  remove(kbId: string) {
    return request.delete<null, ApiResult<null>>(KNOWLEDGE_BASE_URL.byId(kbId));
  },
};
