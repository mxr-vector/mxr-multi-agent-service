import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";
import { STORY_PROJECT_URL } from "./index";
import type { StoryCharacterVO, StoryCharacterArtVO } from "./character";

// ============================================================
// 类型定义（对齐后端 routers/story 契约，字段一律 snake_case）
// ============================================================

/** 项目状态 */
export type StoryProjectStatus = "active" | "archived" | "deleted";

/** 项目当前剧本摘要（详情接口附带） */
export interface StoryCurrentScriptVO {
  id: string;
  version: number;
  title: string | null;
  updated_at: string | null;
}

/** 项目 VO */
export interface StoryProjectVO {
  id: string;
  user_id: string;
  title: string;
  description: string | null;
  cover_image: string | null;
  script_count: number;
  character_count: number;
  art_count: number;
  keyframe_count: number;
  video_count: number;
  session_count: number;
  generation_count: number;
  last_generated_at: string | null;
  status: StoryProjectStatus;
  created_at: string;
  updated_at: string;
}

/** 项目详情 VO（附当前剧本摘要） */
export interface StoryProjectDetailVO extends StoryProjectVO {
  current_script: StoryCurrentScriptVO | null;
}

/** 创建/更新项目请求体 */
export interface StoryProjectPayload {
  title?: string;
  description?: string | null;
  cover_image?: string | null;
  status?: "active" | "archived";
}

/** 项目列表查询参数 */
export interface StoryProjectListParams {
  page?: number;
  size?: number;
  keyword?: string;
  status?: StoryProjectStatus;
}

/** 出演角色列表项（角色信息 + 出演顺序 + 选中立绘 + 内嵌全部立绘） */
export interface StoryCastingVO extends StoryCharacterVO {
  sort_order: number;
  selected_art_ids: string[];
  /** 该角色全部立绘（后端批量内嵌，免前端逐个 detail 放大 N+1） */
  arts: StoryCharacterArtVO[];
}

// ============================================================
// API
// ============================================================

export const projectApi = {
  /** 分页列出本人项目 */
  list(params: StoryProjectListParams = {}) {
    return request.get<PageResult<StoryProjectVO>, ApiResult<PageResult<StoryProjectVO>>>(
      STORY_PROJECT_URL.root,
      { params }
    );
  },
  /** 创建项目 */
  create(payload: StoryProjectPayload) {
    return request.post<StoryProjectVO, ApiResult<StoryProjectVO>>(
      STORY_PROJECT_URL.root,
      payload
    );
  },
  /** 项目详情（含计数与当前剧本摘要） */
  detail(id: string) {
    return request.get<StoryProjectDetailVO, ApiResult<StoryProjectDetailVO>>(
      STORY_PROJECT_URL.byId(id)
    );
  },
  /** 更新项目 */
  update(id: string, payload: StoryProjectPayload) {
    return request.put<StoryProjectVO, ApiResult<StoryProjectVO>>(
      STORY_PROJECT_URL.byId(id),
      payload
    );
  },
  /** 软删项目 */
  remove(id: string) {
    return request.delete<null, ApiResult<null>>(STORY_PROJECT_URL.byId(id));
  },

  // ---------- 出演编排 ----------

  /** 项目出演角色列表 */
  listCasting(projectId: string) {
    return request.get<StoryCastingVO[], ApiResult<StoryCastingVO[]>>(
      STORY_PROJECT_URL.characters(projectId)
    );
  },
  /** 出演登记（引用角色库角色） */
  addCasting(projectId: string, characterId: string) {
    return request.post<StoryCharacterVO, ApiResult<StoryCharacterVO>>(
      STORY_PROJECT_URL.characters(projectId),
      { character_id: characterId }
    );
  },
  /** 移除出演 */
  removeCasting(projectId: string, characterId: string) {
    return request.delete<null, ApiResult<null>>(
      STORY_PROJECT_URL.characterById(projectId, characterId)
    );
  },
  /** 重排出演顺序 */
  sortCasting(projectId: string, characterIds: string[]) {
    return request.put<null, ApiResult<null>>(
      STORY_PROJECT_URL.characterSort(projectId),
      { character_ids: characterIds }
    );
  },
  /** 整体设置项目选中立绘（导出使用） */
  setArtSelection(projectId: string, artIds: string[]) {
    return request.put<unknown, ApiResult<unknown>>(
      STORY_PROJECT_URL.artSelection(projectId),
      { art_ids: artIds }
    );
  },
};
