import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";
import { STORY_PROJECT_URL, STORY_VIDEO_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/story 契约，字段一律 snake_case）
// ============================================================

/** 视频成品 VO（单镜头片段） */
export interface StoryVideoVO {
  id: string;
  project_id: string;
  keyframe_id: string | null;
  script_id: string | null;
  export_package_id: string | null;
  title: string | null;
  episode_no: number | null;
  video_file: string;
  cover_file: string | null;
  duration_ms: number | null;
  file_size: number | null;
  width: number | null;
  height: number | null;
  target_platform: string | null;
  external_task_id: string | null;
  status: string;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

/** 视频登记附属字段（上传时可选填） */
export interface StoryVideoRegisterFields {
  title?: string;
  episode_no?: number;
  keyframe_id?: string;
  script_id?: string;
  export_package_id?: string;
  target_platform?: string;
  external_task_id?: string;
  remark?: string;
}

/** 编辑视频请求体（溯源字段不可改） */
export interface StoryVideoUpdatePayload {
  title?: string | null;
  episode_no?: number | null;
  target_platform?: string | null;
  external_task_id?: string | null;
  remark?: string | null;
}

// ============================================================
// API
// ============================================================

export const videoApi = {
  /** 上传视频片段并登记（服务端抽首帧封面） */
  upload(projectId: string, file: File, fields: StoryVideoRegisterFields = {}) {
    const form = new FormData();
    form.append("file", file);
    if (fields.title) form.append("title", fields.title);
    if (fields.episode_no !== undefined) form.append("episode_no", String(fields.episode_no));
    if (fields.keyframe_id) form.append("keyframe_id", fields.keyframe_id);
    if (fields.script_id) form.append("script_id", fields.script_id);
    if (fields.export_package_id) form.append("export_package_id", fields.export_package_id);
    if (fields.target_platform) form.append("target_platform", fields.target_platform);
    if (fields.external_task_id) form.append("external_task_id", fields.external_task_id);
    if (fields.remark) form.append("remark", fields.remark);
    return request.post<StoryVideoVO, ApiResult<StoryVideoVO>>(
      STORY_PROJECT_URL.videos(projectId),
      form,
      { headers: { "Content-Type": "multipart/form-data" }, timeout: 120000 }
    );
  },
  /** 项目视频列表（可选按关键帧过滤） */
  list(projectId: string, params: { page?: number; size?: number; keyframe_id?: string } = {}) {
    return request.get<PageResult<StoryVideoVO>, ApiResult<PageResult<StoryVideoVO>>>(
      STORY_PROJECT_URL.videos(projectId),
      { params }
    );
  },
  /** 编辑视频登记字段 */
  update(id: string, payload: StoryVideoUpdatePayload) {
    return request.put<StoryVideoVO, ApiResult<StoryVideoVO>>(
      STORY_VIDEO_URL.byId(id),
      payload
    );
  },
  /** 删除视频登记 */
  remove(id: string) {
    return request.delete<null, ApiResult<null>>(STORY_VIDEO_URL.byId(id));
  },
  /** 手动上传封面 */
  uploadCover(id: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    return request.post<StoryVideoVO, ApiResult<StoryVideoVO>>(
      STORY_VIDEO_URL.cover(id),
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
  },
  /** 把视频封面设为项目封面 */
  setProjectCover(id: string) {
    return request.post<unknown, ApiResult<unknown>>(STORY_VIDEO_URL.projectCover(id));
  },
};
