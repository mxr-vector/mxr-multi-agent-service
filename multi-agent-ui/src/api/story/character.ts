import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";
import { STORY_CHARACTER_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/story 契约，字段一律 snake_case）
// ============================================================

/** 角色立绘类型（三视图与正面半身特写为必备参考图） */
export type StoryArtType =
  | "turnaround"
  | "front_bust"
  | "full_body"
  | "half_body"
  | "face"
  | "action"
  | "reference"
  | "other";

/** 角色分类（戏内角色属性） */
export type StoryRoleType =
  | "protagonist"
  | "supporting"
  | "antagonist"
  | "npc"
  | "other";

/** 角色立绘 VO */
export interface StoryCharacterArtVO {
  id: string;
  character_id: string;
  name: string | null;
  image_file: string;
  image_width: number | null;
  image_height: number | null;
  art_type: StoryArtType;
  source: "upload" | "ai";
  prompt: string | null;
  negative_prompt: string | null;
  is_primary: boolean;
  status: string;
  created_at: string;
}

/** 角色 VO（列表） */
export interface StoryCharacterVO {
  id: string;
  user_id: string;
  name: string;
  role_type: StoryRoleType | null;
  profile: Record<string, unknown>;
  style: Record<string, unknown>;
  appearance_prompt: string | null;
  negative_prompt: string | null;
  avatar_file: string | null;
  art_count: number;
  created_at: string;
  updated_at: string;
}

/** 角色详情 VO（附立绘与出演项目） */
export interface StoryCharacterDetailVO extends StoryCharacterVO {
  arts: StoryCharacterArtVO[];
  casting_projects: { project_id: string; title: string }[];
}

/** 创建/更新角色请求体 */
export interface StoryCharacterPayload {
  name?: string;
  role_type?: StoryRoleType | null;
  profile?: Record<string, unknown>;
  style?: Record<string, unknown>;
  appearance_prompt?: string | null;
  negative_prompt?: string | null;
  avatar_file?: string | null;
}

/** 角色列表查询参数 */
export interface StoryCharacterListParams {
  page?: number;
  size?: number;
  keyword?: string;
}

// ============================================================
// API
// ============================================================

export const characterApi = {
  /** 分页列出本人角色库 */
  list(params: StoryCharacterListParams = {}) {
    return request.get<PageResult<StoryCharacterVO>, ApiResult<PageResult<StoryCharacterVO>>>(
      STORY_CHARACTER_URL.root,
      { params }
    );
  },
  /** 创建角色 */
  create(payload: StoryCharacterPayload) {
    return request.post<StoryCharacterVO, ApiResult<StoryCharacterVO>>(
      STORY_CHARACTER_URL.root,
      payload
    );
  },
  /** 角色详情（含立绘与出演项目） */
  detail(id: string) {
    return request.get<StoryCharacterDetailVO, ApiResult<StoryCharacterDetailVO>>(
      STORY_CHARACTER_URL.byId(id)
    );
  },
  /** 更新角色字段 */
  update(id: string, payload: StoryCharacterPayload) {
    return request.put<StoryCharacterVO, ApiResult<StoryCharacterVO>>(
      STORY_CHARACTER_URL.byId(id),
      payload
    );
  },
  /** 删除角色（被出演/关键帧引用时后端拒绝） */
  remove(id: string) {
    return request.delete<null, ApiResult<null>>(STORY_CHARACTER_URL.byId(id));
  },
  /** 上传立绘（首张自动主立绘） */
  uploadArt(characterId: string, file: File, name?: string, artType?: StoryArtType) {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    if (artType) form.append("art_type", artType);
    return request.post<StoryCharacterArtVO, ApiResult<StoryCharacterArtVO>>(
      STORY_CHARACTER_URL.arts(characterId),
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
  },
  /** 设主立绘 */
  setPrimaryArt(characterId: string, artId: string) {
    return request.put<StoryCharacterArtVO, ApiResult<StoryCharacterArtVO>>(
      STORY_CHARACTER_URL.artPrimary(characterId, artId)
    );
  },
  /** 删除立绘 */
  removeArt(characterId: string, artId: string) {
    return request.delete<null, ApiResult<null>>(
      STORY_CHARACTER_URL.artById(characterId, artId)
    );
  },
};
