import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";
import { STORY_KEYFRAME_URL, STORY_PROJECT_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/story 契约，字段一律 snake_case）
// ============================================================

/** 关键帧状态 */
export type StoryKeyframeStatus = "draft" | "generating" | "done" | "failed" | "archived";

/** 关键帧出场角色（含角色名/头像聚合） */
export interface StoryKeyframeCharacterVO {
  keyframe_id: string;
  character_id: string;
  character_art_id: string | null;
  role: string | null;
  character_prompt: string | null;
  sequence: number;
  character_name: string | null;
  character_avatar: string | null;
}

/** 关键帧 VO */
export interface StoryKeyframeVO {
  id: string;
  project_id: string;
  script_id: string | null;
  chapter_no: number | null;
  scene_no: number | null;
  shot_no: number | null;
  name: string | null;
  scene_description: string | null;
  visual_description: string | null;
  camera_description: string | null;
  lighting_description: string | null;
  style_description: string | null;
  prompt: string;
  negative_prompt: string | null;
  reference_images: unknown[];
  image_file: string | null;
  status: StoryKeyframeStatus;
  created_at: string;
  updated_at: string;
  /** 列表/详情附带 */
  characters: StoryKeyframeCharacterVO[];
  /** 导出选择状态（编排层），供「导出选择」对话框回显 */
  is_selected: boolean;
  selection_order: number;
}

/** 出场角色条目（登记/设置用） */
export interface StoryKeyframeCharacterEntry {
  character_id: string;
  character_art_id?: string | null;
  role?: string | null;
  character_prompt?: string | null;
}

/** 创建关键帧请求体 */
export interface StoryKeyframeCreatePayload {
  prompt: string;
  script_id?: string | null;
  chapter_no?: number | null;
  scene_no?: number | null;
  shot_no?: number | null;
  name?: string | null;
  scene_description?: string | null;
  visual_description?: string | null;
  camera_description?: string | null;
  lighting_description?: string | null;
  style_description?: string | null;
  negative_prompt?: string | null;
  reference_images?: unknown[];
  characters?: StoryKeyframeCharacterEntry[];
}

/** 更新关键帧请求体（图片经 uploadImage 端点维护，不接受路径直写） */
export interface StoryKeyframeUpdatePayload extends Partial<StoryKeyframeCreatePayload> {
  status?: StoryKeyframeStatus;
}

// ============================================================
// API
// ============================================================

export const keyframeApi = {
  /** 项目关键帧列表（含出场角色摘要） */
  list(projectId: string, params: { page?: number; size?: number } = {}) {
    return request.get<PageResult<StoryKeyframeVO>, ApiResult<PageResult<StoryKeyframeVO>>>(
      STORY_PROJECT_URL.keyframes(projectId),
      { params }
    );
  },
  /** 创建关键帧 */
  create(projectId: string, payload: StoryKeyframeCreatePayload) {
    return request.post<StoryKeyframeVO, ApiResult<StoryKeyframeVO>>(
      STORY_PROJECT_URL.keyframes(projectId),
      payload
    );
  },
  /** 关键帧详情 */
  detail(id: string) {
    return request.get<StoryKeyframeVO, ApiResult<StoryKeyframeVO>>(
      STORY_KEYFRAME_URL.byId(id)
    );
  },
  /** 编辑关键帧 */
  update(id: string, payload: StoryKeyframeUpdatePayload) {
    return request.put<StoryKeyframeVO, ApiResult<StoryKeyframeVO>>(
      STORY_KEYFRAME_URL.byId(id),
      payload
    );
  },
  /** 删除关键帧 */
  remove(id: string) {
    return request.delete<null, ApiResult<null>>(STORY_KEYFRAME_URL.byId(id));
  },
  /** 上传/替换关键帧图片（存入 项目名/关键帧名 目录） */
  uploadImage(id: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    return request.post<StoryKeyframeVO, ApiResult<StoryKeyframeVO>>(
      STORY_KEYFRAME_URL.image(id),
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
  },
  /** 整体设置出场角色 */
  setCharacters(id: string, characters: StoryKeyframeCharacterEntry[]) {
    return request.put<StoryKeyframeVO, ApiResult<StoryKeyframeVO>>(
      STORY_KEYFRAME_URL.characters(id),
      { characters }
    );
  },
  /** 整体设置导出选中关键帧 */
  setSelection(projectId: string, keyframeIds: string[]) {
    return request.put<unknown, ApiResult<unknown>>(
      STORY_PROJECT_URL.keyframeSelection(projectId),
      { keyframe_ids: keyframeIds }
    );
  },
};
