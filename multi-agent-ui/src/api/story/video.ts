import request, { type ApiResult } from "@/utils/request";
import type { PageResult } from "@/api/rag";
import { STORY_PROJECT_URL, STORY_VIDEO_URL } from "./index";

// ============================================================
// 类型定义（对齐后端 routers/story 契约，字段一律 snake_case）
// ============================================================

/** 视频来源：外部上传回收 / 视频模型生成 */
export type StoryVideoSource = "upload" | "generated";

/** 视频状态：生成中排队 / 生成中 / 完成 / 失败 / 已中止 */
export type StoryVideoStatus =
  | "queued"
  | "generating"
  | "done"
  | "failed"
  | "cancelled";

/** 视频成品 VO（单镜头片段） */
export interface StoryVideoVO {
  id: string;
  project_id: string;
  keyframe_id: string | null;
  script_id: string | null;
  export_package_id: string | null;
  source: StoryVideoSource;
  title: string | null;
  episode_no: number | null;
  /** 生成中为空，完成后回填 */
  video_file: string | null;
  cover_file: string | null;
  duration_ms: number | null;
  file_size: number | null;
  width: number | null;
  height: number | null;
  prompt?: string | null;
  negative_prompt?: string | null;
  provider: string | null;
  model: string | null;
  generation_params?: Record<string, unknown> | null;
  target_platform: string | null;
  external_task_id: string | null;
  status: StoryVideoStatus;
  error_message: string | null;
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

/** 章节编排中的文本/图片块：图片落在剧本对应关键帧位置 */
export type StoryVideoPlanBlock =
  | { type: "text"; text: string }
  | {
      type: "image";
      keyframe_id: string;
      image_file: string | null;
      has_image: boolean;
      label: string;
      name: string;
      scene_no: number | null;
      shot_no: number | null;
    };

/** 章节编排中的镜头元数据 */
export interface StoryVideoPlanShot {
  keyframe_id: string;
  scene_no: number | null;
  shot_no: number | null;
  name: string;
  image_file: string | null;
  has_image: boolean;
  shot_content: string;
}

/** 章节化编排中的一个生成单元（一章生成一个片段） */
export interface StoryVideoPlanChapter {
  chapter_no: number | null;
  title: string;
  /** 章节完整正文 */
  content: string;
  /** 按剧本顺序内嵌关键帧的文本/图片块 */
  blocks: StoryVideoPlanBlock[];
  /** 自动组合、可编辑的整章提示词 */
  prompt: string;
  /** 本章参考图对应的关键帧顺序 */
  keyframe_ids: string[];
  shots: StoryVideoPlanShot[];
  /** 是否为剧本中未匹配到章节的兜底分组 */
  unmatched: boolean;
}

/** 当前剧本与章节化编排结果 */
export interface StoryVideoPlan {
  script: {
    id: string;
    version: number;
    title: string | null;
    is_current: boolean;
  } | null;
  chapters: StoryVideoPlanChapter[];
}

/** 章节片段生成请求体：一章一份提示词 + 该章全部关键帧 */
export interface StoryChapterVideoGeneratePayload {
  chapter_no?: number | null;
  title?: string;
  prompt: string;
  keyframe_ids: string[];
  chapter_content?: string | null;
  /** 是否把关键帧作为参考图提交 */
  use_images?: boolean;
  resolution?: string;
  ratio?: string;
  duration?: number;
  /** 是否自动取上一集已完成片段的尾帧作首帧 */
  link_previous?: boolean;
}

/** 串行链中的单个章节提交项 */
export interface StoryVideoChainChapterPayload {
  chapter_no?: number | null;
  title?: string;
  prompt: string;
  keyframe_ids: string[];
  chapter_content?: string | null;
}

/** 串行链生成请求体：按集顺序逐章生成，下一章首帧取上一章成片尾帧 */
export interface StoryChapterVideoChainPayload {
  chapters: StoryVideoChainChapterPayload[];
  use_images?: boolean;
  resolution?: string;
  ratio?: string;
  duration?: number;
}

/** 串行链中单章实时状态 */
export interface StoryVideoChainChapterState {
  video_id: string;
  chapter_no: number | null;
  title: string;
  status: StoryVideoStatus | "unknown";
}

/** 串行链实时状态（章节状态以数据库为准） */
export interface StoryVideoChainStatus {
  running: boolean;
  chain_id?: string;
  total: number;
  finished?: number;
  success?: number;
  failed?: number;
  cancelled?: number;
  cursor?: number;
  current_chapter_no?: number | null;
  chapters: StoryVideoChainChapterState[];
}

/** 生成面板公共配置（后端 CFG.video.extra 兜底值，不含敏感凭证） */
export interface StoryVideoGenerationOptions {
  model: string;
  resolution: string;
  ratio: string;
  duration: number;
  max_concurrent: number;
}

// ============================================================
// API
// ============================================================

export const videoApi = {
  /** 生成面板公共配置 */
  generationOptions() {
    return request.get<StoryVideoGenerationOptions, ApiResult<StoryVideoGenerationOptions>>(
      STORY_VIDEO_URL.options
    );
  },
  /** 章节化编排：自动对齐剧本章节/镜头文本与关键帧 */
  plan(projectId: string) {
    return request.get<StoryVideoPlan, ApiResult<StoryVideoPlan>>(
      STORY_PROJECT_URL.videoPlan(projectId)
    );
  },
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
  /** 项目视频列表（可选按关键帧/来源/状态过滤） */
  list(
    projectId: string,
    params: {
      page?: number;
      size?: number;
      keyframe_id?: string;
      source?: StoryVideoSource;
      status?: StoryVideoStatus;
      /** 精简模式：省略提示词/生成参数等大字段 */
      brief?: boolean;
    } = {}
  ) {
    return request.get<PageResult<StoryVideoVO>, ApiResult<PageResult<StoryVideoVO>>>(
      STORY_PROJECT_URL.videos(projectId),
      { params }
    );
  },
  /** 生成一个章节片段（一次提交该章提示词与全部关键帧参考图） */
  generate(projectId: string, payload: StoryChapterVideoGeneratePayload) {
    return request.post<StoryVideoVO, ApiResult<StoryVideoVO>>(
      STORY_PROJECT_URL.generateVideos(projectId),
      payload
    );
  },
  /** 串行生成章节视频：逐章执行，上一章成片尾帧作为下一章首帧 */
  generateChain(projectId: string, payload: StoryChapterVideoChainPayload) {
    return request.post<
      {
        chain_id: string;
        total: number;
        chapters: Array<{
          video_id: string;
          chapter_no: number | null;
          title: string;
        }>;
      },
      ApiResult<{
        chain_id: string;
        total: number;
        chapters: Array<{
          video_id: string;
          chapter_no: number | null;
          title: string;
        }>;
      }>
    >(STORY_PROJECT_URL.generateVideoChain(projectId), payload);
  },
  /** 串行链实时状态 */
  chainStatus(projectId: string) {
    return request.get<StoryVideoChainStatus, ApiResult<StoryVideoChainStatus>>(
      STORY_PROJECT_URL.videoChainStatus(projectId)
    );
  },
  /** 中止在途视频生成 */
  stop(id: string) {
    return request.post<{ cancelled: boolean }, ApiResult<{ cancelled: boolean }>>(
      STORY_VIDEO_URL.stop(id)
    );
  },
  /** 中止项目下全部在途视频任务 */
  stopAll(projectId: string) {
    return request.post<{ stopped_count: number }, ApiResult<{ stopped_count: number }>>(
      STORY_PROJECT_URL.stopAllVideos(projectId)
    );
  },
  /** 编辑视频登记字段 */
  update(id: string, payload: StoryVideoUpdatePayload) {
    return request.put<StoryVideoVO, ApiResult<StoryVideoVO>>(STORY_VIDEO_URL.byId(id), payload);
  },
  /** 删除视频登记 */
  remove(id: string) {
    return request.delete<null, ApiResult<null>>(STORY_VIDEO_URL.byId(id));
  },
  /** 手动上传封面 */
  uploadCover(id: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    return request.post<StoryVideoVO, ApiResult<StoryVideoVO>>(STORY_VIDEO_URL.cover(id), form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  /** 把视频封面设为项目封面 */
  setProjectCover(id: string) {
    return request.post<unknown, ApiResult<unknown>>(STORY_VIDEO_URL.projectCover(id));
  },
};
