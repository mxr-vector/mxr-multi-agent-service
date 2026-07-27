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

/** 统计查询参数 */
export interface RagStatsParams {
  /** 按部门集合过滤（IN 匹配，传部门子树 id 集合；仅 data_scope=all 生效） */
  dept_ids?: string[];
}

/** RAG 统计 API：统一通过 statsApi.xx() 调用 */
export const statsApi = {
  /** 获取 RAG 统计：知识库数、文档总数、分块总数（口径与知识库列表部门边界一致） */
  overview(params: RagStatsParams = {}) {
    return request.get<RagStats, ApiResult<RagStats>>(STATS_URL.root, { params });
  },
};
