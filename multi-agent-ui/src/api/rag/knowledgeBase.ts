import request, { type ApiResult } from "@/api/request";
import { KNOWLEDGE_BASE_URL } from "./index";

/** 知识库实体（对应后端 rag_knowledge_bases.to_dict） */
export interface KnowledgeBase {
  id: string;
  name: string;
  code: string;
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

/** 创建知识库请求体（仅元数据，不创建 Qdrant collection） */
export interface KnowledgeBaseCreatePayload {
  name: string;
  code: string;
  qdrant_collection: string;
  description?: string | null;
  category_id?: string | null;
  icon?: string | null;
  embedding_provider?: string | null;
  embedding_model?: string | null;
  embedding_dim?: number | null;
  visibility?: string;
  owner?: string | null;
}

/** 更新知识库请求体（仅可编辑元数据；code/qdrant_collection/embedding_* 不可变） */
export interface KnowledgeBaseUpdatePayload {
  name?: string;
  description?: string | null;
  category_id?: string | null;
  icon?: string | null;
  visibility?: string;
  owner?: string | null;
  status?: string;
}

/** 创建知识库（code 重复时返回失败而非 500） */
export function createKnowledgeBase(payload: KnowledgeBaseCreatePayload) {
  return request.post<KnowledgeBase, ApiResult<KnowledgeBase>>(KNOWLEDGE_BASE_URL.root, payload);
}

/** 列出知识库（排除软删除的），可选按 categoryId 过滤 */
export function listKnowledgeBases(categoryId?: string) {
  return request.get<KnowledgeBase[], ApiResult<KnowledgeBase[]>>(KNOWLEDGE_BASE_URL.root, {
    params: { category_id: categoryId },
  });
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
