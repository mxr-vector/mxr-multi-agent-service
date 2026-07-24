import request, { type ApiResult } from "@/utils/request";
import { CHUNK_URL, type PageResult } from "./index";

/** 分块实体（对应后端 rag_chunks.to_dict） */
export interface Chunk {
  id: string;
  /** 多租户隔离标识，由服务端注入（缺省 'default'），不可变 */
  tenant_id: string;
  document_id: string;
  parent_chunk_id: string | null;
  document_version: number;
  /** 0 叶块（入 Qdrant） / 1 父块（仅 PG，用于回写上下文） */
  level: number;
  chunk_index: number;
  content: string;
  token_count: number | null;
  char_start: number | null;
  char_end: number | null;
  chapter_title: string | null;
  page_start: number | null;
  page_end: number | null;
  content_hash: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

/** 分页列出分块参数 */
export interface ChunkListParams {
  /** 按文档过滤 */
  document_id: string;
  /** 按层级过滤（0 叶块 / 1 父块） */
  level?: number;
  /** 按文档版本过滤 */
  document_version?: number;
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 50） */
  size?: number;
}

/** 按文档分页列出分块，可选 level/document_version 过滤，按 chunk_index 升序 */
export function listChunks(params: ChunkListParams) {
  return request.get<PageResult<Chunk>, ApiResult<PageResult<Chunk>>>(CHUNK_URL.root, { params });
}

/** 按 id 获取分块 */
export function getChunk(chunkId: string) {
  return request.get<Chunk, ApiResult<Chunk>>(CHUNK_URL.byId(chunkId));
}
