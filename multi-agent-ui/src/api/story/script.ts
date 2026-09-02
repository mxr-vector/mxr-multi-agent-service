import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";
import { STORY_PROJECT_URL, STORY_SCRIPT_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/story 契约，字段一律 snake_case）
// ============================================================

/** 剧本来源 */
export type StoryScriptSource = "ai" | "user" | "upload";

/** 剧本版本 VO */
export interface StoryScriptVO {
  id: string;
  project_id: string;
  version: number;
  title: string | null;
  content: string;
  source: StoryScriptSource;
  is_current: boolean;
  created_at: string;
  updated_at: string;
}

/** 保存新版本请求体 */
export interface StoryScriptSavePayload {
  content: string;
  title?: string | null;
  source?: StoryScriptSource;
  set_current?: boolean;
}

/** 编辑既有版本请求体 */
export interface StoryScriptUpdatePayload {
  content?: string;
  title?: string | null;
}

// ============================================================
// API
// ============================================================

export const scriptApi = {
  /** 项目剧本历史列表（版本倒序） */
  list(projectId: string, params: { page?: number; size?: number } = {}) {
    return request.get<PageResult<StoryScriptVO>, ApiResult<PageResult<StoryScriptVO>>>(
      STORY_PROJECT_URL.scripts(projectId),
      { params }
    );
  },
  /** 保存新剧本版本 */
  save(projectId: string, payload: StoryScriptSavePayload) {
    return request.post<StoryScriptVO, ApiResult<StoryScriptVO>>(
      STORY_PROJECT_URL.scripts(projectId),
      payload
    );
  },
  /** 切换当前版本（先复位再置位） */
  switchCurrent(scriptId: string) {
    return request.put<StoryScriptVO, ApiResult<StoryScriptVO>>(STORY_SCRIPT_URL.current(scriptId));
  },
  /** 编辑既有版本内容/标题 */
  update(scriptId: string, payload: StoryScriptUpdatePayload) {
    return request.put<StoryScriptVO, ApiResult<StoryScriptVO>>(
      STORY_SCRIPT_URL.byId(scriptId),
      payload
    );
  },
};
