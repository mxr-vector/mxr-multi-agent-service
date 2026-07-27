import request, { type ApiResult } from "@/utils/request";
import { STATS_URL } from "./index";

/** RAG 全局统计（对应后端 service/rag/stats.py::overview） */
export interface RagStats {
  /** 知识库数量（排除软删除的） */
  knowledge_base_count: number;
  /** 文档总数（各知识库 document_count 之和） */
  document_count: number;
  /** 分块总数（各知识库 total_chunk_count 之和） */
  total_chunk_count: number;
}

/** RAG 统计 API：统一通过 statsApi.xx() 调用 */
export const statsApi = {
  /** 获取 RAG 全局统计：知识库数、文档总数、分块总数 */
  overview() {
    return request.get<RagStats, ApiResult<RagStats>>(STATS_URL.root);
  },
};
