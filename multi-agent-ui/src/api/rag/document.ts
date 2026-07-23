import request, { type ApiResult } from "@/api/request";
import { DOCUMENT_URL } from "./index";

/** 文档实体（对应后端 rag_documents.to_dict） */
export interface RagDocument {
  id: string;
  /** 多租户隔离标识，由服务端注入（缺省 'default'），不可变 */
  tenant_id: string;
  knowledge_base_id: string;
  source_uri: string | null;
  source_system: string | null;
  title: string | null;
  doc_type: string | null;
  content: string | null;
  content_hash: string | null;
  metadata: Record<string, unknown>;
  source_updated_at: string | null;
  valid_from: string;
  valid_until: string | null;
  last_verified_at: string | null;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

/** 上传文档参数（multipart/form-data） */
export interface DocumentUploadParams {
  /** 待上传文件（pdf/markdown/excel/docx） */
  file: File;
  /** 目标知识库 id */
  knowledge_base_id: string;
  /** 来源标识，缺省用文件名 */
  source_uri?: string;
  /** 来源系统 */
  source_system?: string;
  /** 文档标题，缺省用文件名 */
  title?: string;
}

/** 分页列出文档参数 */
export interface DocumentListParams {
  /** 按知识库过滤 */
  knowledge_base_id: string;
  /** 每页数量（1-200，默认 20） */
  limit?: number;
  /** 偏移量（默认 0） */
  offset?: number;
}

/** 更新文档请求体（仅可编辑元数据；内容/哈希/版本/归属/状态不可变） */
export interface DocumentUpdatePayload {
  title?: string;
  source_uri?: string;
  source_system?: string;
  doc_type?: string;
  metadata?: Record<string, unknown>;
  source_updated_at?: string;
  valid_from?: string;
  valid_until?: string;
  last_verified_at?: string;
}

/** 上传文件：解析 + 两级切块 + 落库（不向量化）。未变化的重复上传是幂等 no-op */
export function uploadDocument(params: DocumentUploadParams) {
  const form = new FormData();
  form.append("file", params.file);
  form.append("knowledge_base_id", params.knowledge_base_id);
  if (params.source_uri != null) form.append("source_uri", params.source_uri);
  if (params.source_system != null) form.append("source_system", params.source_system);
  if (params.title != null) form.append("title", params.title);
  return request.post<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.upload, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

/** 单独触发向量化：把当前版本 level 0 叶块写入知识库的 Qdrant 集合 */
export function vectorizeDocument(docId: string) {
  return request.post<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.vectorize(docId));
}

/** 按知识库分页列出文档（排除软删除的） */
export function listDocuments(params: DocumentListParams) {
  return request.get<RagDocument[], ApiResult<RagDocument[]>>(DOCUMENT_URL.root, {
    params,
  });
}

/** 按 id 获取文档 */
export function getDocument(docId: string) {
  return request.get<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.byId(docId));
}

/** 仅元数据更新；不触碰内容/哈希/版本/归属/状态，不再切块或向量化 */
export function updateDocument(docId: string, payload: DocumentUpdatePayload) {
  return request.put<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.byId(docId), payload);
}
