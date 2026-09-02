/**
 * 剧本模块后端接口地址维护中心。
 *
 * request 实例的 baseURL 为 VITE_APP_BASE_API（如 /dev-api），经 Vite 代理转发时会剥离该前缀，
 * 因此这里的路径直接对应服务端 routers/story 下的路由（统一前缀 /story）。
 */

/** 后端剧本路由前缀（routers/story） */
const BASE = "/story";

/** 角色库接口地址 */
export const STORY_CHARACTER_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/characters`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/characters/${id}`,
  /** 立绘上传（multipart） */
  arts: (characterId: string) => `${BASE}/characters/${characterId}/arts`,
  /** 设主立绘 */
  artPrimary: (characterId: string, artId: string) =>
    `${BASE}/characters/${characterId}/arts/${artId}/primary`,
  /** 立绘删除 */
  artById: (characterId: string, artId: string) =>
    `${BASE}/characters/${characterId}/arts/${artId}`,
} as const;

/** 项目管理接口地址 */
export const STORY_PROJECT_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/projects`,
  /** 详情 / 更新 / 删除（软删） */
  byId: (id: string) => `${BASE}/projects/${id}`,
  /** 出演角色列表 / 出演登记 */
  characters: (projectId: string) => `${BASE}/projects/${projectId}/characters`,
  /** 移除出演 / 出演排序（/characters/sort 为 PUT） */
  characterById: (projectId: string, characterId: string) =>
    `${BASE}/projects/${projectId}/characters/${characterId}`,
  /** 出演排序 */
  characterSort: (projectId: string) => `${BASE}/projects/${projectId}/characters/sort`,
  /** 选中立绘（导出使用） */
  artSelection: (projectId: string) => `${BASE}/projects/${projectId}/art-selection`,
  /** 剧本列表 / 保存新版本 */
  scripts: (projectId: string) => `${BASE}/projects/${projectId}/scripts`,
  /** 关键帧列表 / 创建 */
  keyframes: (projectId: string) => `${BASE}/projects/${projectId}/keyframes`,
  /** 导出选中关键帧 */
  keyframeSelection: (projectId: string) => `${BASE}/projects/${projectId}/keyframe-selection`,
  /** 视频上传登记 / 列表 */
  videos: (projectId: string) => `${BASE}/projects/${projectId}/videos`,
  /** 导出包生成 / 列表 */
  exports: (projectId: string) => `${BASE}/projects/${projectId}/exports`,
} as const;

/** 剧本版本接口地址 */
export const STORY_SCRIPT_URL = {
  /** 切换当前版本 */
  current: (scriptId: string) => `${BASE}/scripts/${scriptId}/current`,
  /** 编辑既有版本 */
  byId: (scriptId: string) => `${BASE}/scripts/${scriptId}`,
} as const;

/** 关键帧接口地址 */
export const STORY_KEYFRAME_URL = {
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/keyframes/${id}`,
  /** 整体设置出场角色 */
  characters: (id: string) => `${BASE}/keyframes/${id}/characters`,
  /** 上传/替换关键帧图片 */
  image: (id: string) => `${BASE}/keyframes/${id}/image`,
} as const;

/** 视频成品接口地址 */
export const STORY_VIDEO_URL = {
  /** 编辑 / 删除 */
  byId: (id: string) => `${BASE}/videos/${id}`,
  /** 手动上传封面（multipart） */
  cover: (id: string) => `${BASE}/videos/${id}/cover`,
  /** 设为项目封面 */
  projectCover: (id: string) => `${BASE}/videos/${id}/project-cover`,
} as const;

/** 导出包接口地址 */
export const STORY_EXPORT_URL = {
  /** 详情 */
  byId: (id: string) => `${BASE}/exports/${id}`,
} as const;

/** 上传/预览文件的公开访问基址（静态挂载 {BASE_URL}/public/files，免 token） */
export const STORY_FILE_BASE = `${import.meta.env.VITE_APP_BASE_API}/public/files`;

/** 相对路径转公开访问地址；空值原样返回 */
export function storyFileUrl(relative?: string | null): string {
  return relative ? `${STORY_FILE_BASE}/${relative}` : "";
}

/** 分页结果最小契约（与 @/api/rag 的 PageResult 对齐，避免循环依赖仅取所需字段） */
interface PageLike<T> {
  items?: T[];
  total?: number;
}

/**
 * 按后端分页上限（size=100）连续拉取全部条目，避免长列表被静默截断。
 * load 为单页请求函数；maxPages 为安全上限（默认 50 页 = 5000 条）。
 */
export async function collectPages<T>(
  load: (params: { page: number; size: number }) => Promise<{ data: PageLike<T> | null }>,
  maxPages = 50
): Promise<T[]> {
  const size = 100;
  const all: T[] = [];
  for (let page = 1; page <= maxPages; page++) {
    const res = await load({ page, size });
    const items = res.data?.items ?? [];
    all.push(...items);
    const total = res.data?.total ?? all.length;
    if (!items.length || all.length >= total) break;
  }
  return all;
}

// 统一出口：业务侧可直接从 "@/api/story" 导入 API 对象与类型
export * from "./character";
export * from "./project";
export * from "./script";
export * from "./keyframe";
export * from "./video";
export * from "./export";
