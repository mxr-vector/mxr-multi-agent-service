import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";
import { STORY_EXPORT_URL, STORY_PROJECT_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/story 契约，字段一律 snake_case）
// ============================================================

/** 导出包 VO（不可变快照） */
export interface StoryExportPackageVO {
  id: string;
  project_id: string;
  name: string;
  export_type: string;
  target_platform: string | null;
  script_id: string | null;
  payload: Record<string, unknown>;
  prompt_text: string;
  copy_text: string | null;
  markdown_text: string | null;
  template_version: string | null;
  version: number;
  created_at: string;
}

/** 导出请求体 */
export interface StoryExportPayload {
  name?: string;
  target_platform?: string;
}

// ============================================================
// API
// ============================================================

export const exportApi = {
  /** 生成导出包（当前剧本 + 出演角色 + 被选关键帧） */
  create(projectId: string, payload: StoryExportPayload = {}) {
    return request.post<StoryExportPackageVO, ApiResult<StoryExportPackageVO>>(
      STORY_PROJECT_URL.exports(projectId),
      payload
    );
  },
  /** 项目导出包列表（版本倒序） */
  list(projectId: string, params: { page?: number; size?: number } = {}) {
    return request.get<
      PageResult<StoryExportPackageVO>,
      ApiResult<PageResult<StoryExportPackageVO>>
    >(STORY_PROJECT_URL.exports(projectId), { params });
  },
  /** 导出包详情 */
  detail(id: string) {
    return request.get<StoryExportPackageVO, ApiResult<StoryExportPackageVO>>(
      STORY_EXPORT_URL.byId(id)
    );
  },
};
