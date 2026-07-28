import request, { type ApiResult } from "@/utils/request";
import { DOCUMENT_URL, type PageResult } from "./index";

/** 文档实体（对应后端 rag_documents.to_dict） */
export interface RagDocument {
  id: string;
  /** 归属组织/部门（逻辑指向 sys_dept.id，空字符串表示未归属），由服务端注入，不可变 */
  dept_id: string;
  knowledge_base_id: string;
  folder_id: string | null;
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
  /** 同一知识库内的文件夹 id */
  folder_id?: string | null;
  /** 来源标识，缺省用文件名 */
  source_uri?: string;
  /** 来源系统 */
  source_system?: string;
  /** 文档标题，缺省用文件名 */
  title?: string;
  /** 有效期起始时间（ISO 字符串），缺省用服务端 now() */
  valid_from?: string;
  /** 有效期截止时间（ISO 字符串），缺省表示长期有效 */
  valid_until?: string;
  /** 备注，存入 metadata.remark */
  remark?: string;
  /** 归属部门（仅 data_scope=all 生效，须为已存在部门）；缺省由服务端按用户上下文注入 */
  dept_id?: string | null;
}

/** 分页列出文档参数 */
export interface DocumentListParams {
  /** 按知识库过滤 */
  knowledge_base_id: string;
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按状态过滤 */
  status?: string;
  /** 按部门集合过滤（IN 匹配，传部门子树 id 集合；仅 data_scope=all 生效） */
  dept_ids?: string[];
}

/** 更新文档请求体（仅可编辑元数据；内容/哈希/版本/归属/状态不可变） */
export interface DocumentUpdatePayload {
  title?: string;
  folder_id?: string | null;
  source_uri?: string;
  source_system?: string;
  doc_type?: string;
  metadata?: Record<string, unknown>;
  source_updated_at?: string;
  valid_from?: string;
  valid_until?: string;
  last_verified_at?: string;
}

/** 批量状态查询结果项（轮询用，未知 id 不在结果中） */
export interface DocumentStatusItem {
  id: string;
  status: string;
}

/** 文档管理 API：统一通过 documentApi.xx() 调用 */
export const documentApi = {
  /** 上传文件：解析 + 两级切块 + 落库（不向量化）。未变化的重复上传是幂等 no-op */
  upload(params: DocumentUploadParams) {
    const form = new FormData();
    form.append("file", params.file);
    form.append("knowledge_base_id", params.knowledge_base_id);
    if (params.folder_id != null) form.append("folder_id", params.folder_id);
    if (params.source_uri != null) form.append("source_uri", params.source_uri);
    if (params.source_system != null) form.append("source_system", params.source_system);
    if (params.title != null) form.append("title", params.title);
    if (params.valid_from != null) form.append("valid_from", params.valid_from);
    if (params.valid_until != null) form.append("valid_until", params.valid_until);
    if (params.remark != null) form.append("remark", params.remark);
    if (params.dept_id != null) form.append("dept_id", params.dept_id);
    return request.post<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.upload, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  /** 单独触发向量化（异步）：置 reindexing 后立即返回，后台完成 embed/写 Qdrant */
  vectorize(docId: string) {
    return request.post<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.vectorize(docId));
  },

  /** 批量查询文档向量化状态（轮询）：ids 逗号分隔，上限 200 */
  batchStatus(ids: string[]) {
    return request.get<DocumentStatusItem[], ApiResult<DocumentStatusItem[]>>(DOCUMENT_URL.status, {
      params: { ids: ids.join(",") },
    });
  },

  /** 按知识库分页列出文档（排除软删除的），可选按 status 过滤 */
  list(params: DocumentListParams) {
    return request.get<PageResult<RagDocument>, ApiResult<PageResult<RagDocument>>>(
      DOCUMENT_URL.root,
      { params }
    );
  },

  /** 按 id 获取文档 */
  get(docId: string) {
    return request.get<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.byId(docId));
  },

  /** 仅元数据更新；不触碰内容/哈希/版本/归属/状态，不再切块或向量化 */
  update(docId: string, payload: DocumentUpdatePayload) {
    return request.put<RagDocument, ApiResult<RagDocument>>(DOCUMENT_URL.byId(docId), payload);
  },
};
