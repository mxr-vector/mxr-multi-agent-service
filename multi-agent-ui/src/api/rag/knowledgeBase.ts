import request, { type ApiResult } from "@/utils/request";
import { KNOWLEDGE_BASE_URL, type PageResult } from "./index";

/** 知识库实体（对应后端 rag_knowledge_bases.to_dict） */
export interface KnowledgeBase {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  category_id: string | null;
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

/** 创建知识库请求体（仅元数据，不创建 Qdrant collection；tenant_id 由服务端注入；qdrant_collection 由后端由 id 派生） */
export interface KnowledgeBaseCreatePayload {
  name: string;
  description?: string | null;
  category_id?: string | null;
  icon?: string | null;
  embedding_provider?: string | null;
  embedding_model?: string | null;
  embedding_dim?: number | null;
  visibility?: string;
  owner?: string | null;
}

/** 更新知识库请求体（仅可编辑元数据；tenant_id/qdrant_collection/embedding_* 不可变） */
export interface KnowledgeBaseUpdatePayload {
  name?: string;
  description?: string | null;
  category_id?: string | null;
  icon?: string | null;
  visibility?: string;
  owner?: string | null;
  status?: string;
}

/** 创建知识库（tenant_id 由服务端注入） */
export function createKnowledgeBase(payload: KnowledgeBaseCreatePayload) {
  return request.post<KnowledgeBase, ApiResult<KnowledgeBase>>(KNOWLEDGE_BASE_URL.root, payload);
}

/** 分页列出知识库参数 */
export interface KnowledgeBaseListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按分类过滤 */
  category_id?: string;
  /** 按名称/描述模糊搜索 */
  keyword?: string;
}

/** 分页列出知识库（排除软删除的），可选按分类/关键词过滤 */
export function listKnowledgeBases(params: KnowledgeBaseListParams = {}) {
  return request.get<PageResult<KnowledgeBase>, ApiResult<PageResult<KnowledgeBase>>>(
    KNOWLEDGE_BASE_URL.root,
    { params }
  );
}

/** 按 id 获取知识库 */
export function getKnowledgeBase(kbId: string) {
  return request.get<KnowledgeBase, ApiResult<KnowledgeBase>>(KNOWLEDGE_BASE_URL.byId(kbId));
}

/** 仅元数据更新（含 status active↔archived）；不可变字段不受影响 */
export function updateKnowledgeBase(kbId: string, payload: KnowledgeBaseUpdatePayload) {
  return request.put<KnowledgeBase, ApiResult<KnowledgeBase>>(
    KNOWLEDGE_BASE_URL.byId(kbId),
    payload
  );
}

/** 软删除：置 status='deleted'，随后不再出现在列表中 */
export function deleteKnowledgeBase(kbId: string) {
  return request.delete<null, ApiResult<null>>(KNOWLEDGE_BASE_URL.byId(kbId));
}
