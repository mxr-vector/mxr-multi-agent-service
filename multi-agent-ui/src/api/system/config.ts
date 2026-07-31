import request, { type ApiResult } from "@/utils/request";
import { CONFIG_URL, type PageResult } from "./index";

/** 参数配置实体（对应后端 sys_config.to_dict） */
export interface Config {
  id: string;
  name: string;
  /** 参数键（如 'sys.user.init_password'），全局唯一 */
  key: string;
  value: string | null;
  /** 内置参数删除保护标记，创建后不可变；禁删但允许更新 value */
  is_builtin: boolean;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

/** 创建参数请求体（key 全局唯一，is_builtin 创建后不可变） */
export interface ConfigCreatePayload {
  name: string;
  key: string;
  value?: string | null;
  is_builtin?: boolean;
  remark?: string | null;
}

/** 更新参数请求体（仅提供的字段会被更新，is_builtin 不可变） */
export interface ConfigUpdatePayload {
  name?: string;
  key?: string;
  value?: string | null;
  remark?: string | null;
}

/** 更新返回体：在参数基础上附带热更新是否生效标识 */
export type ConfigUpdateResult = Config & { refreshed?: boolean };

/** 分页列出参数配置参数 */
export interface ConfigListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按名称/参数键模糊搜索 */
  keyword?: string;
}

/** 参数配置管理 API：统一通过 configApi.xx() 调用 */
export const configApi = {
  /** 创建参数配置（key 全局唯一） */
  create(payload: ConfigCreatePayload) {
    return request.post<Config, ApiResult<Config>>(CONFIG_URL.root, payload);
  },

  /** 真分页列出参数配置，可选按关键词过滤 */
  list(params: ConfigListParams = {}) {
    return request.get<PageResult<Config>, ApiResult<PageResult<Config>>>(CONFIG_URL.root, {
      params,
    });
  },

  /** 按 id 获取参数配置 */
  get(configId: string) {
    return request.get<Config, ApiResult<Config>>(CONFIG_URL.byId(configId));
  },

  /** 批量读取白名单内置标量运行参数（RAG_* / CHAT_*），供模型配置页运行参数区域渲染 */
  listScalars() {
    return request.get<Config[], ApiResult<Config[]>>(CONFIG_URL.scalars);
  },

  /** 按 key 精确查询参数（供业务读取配置值） */
  getByKey(key: string) {
    return request.get<Config, ApiResult<Config>>(CONFIG_URL.byKey(key));
  },

  /** 更新参数配置（is_builtin 不可变，变更 key 时后端校验唯一）；成功后后端触发快照刷新，结果经 data.refreshed 透出 */
  update(configId: string, payload: ConfigUpdatePayload) {
    return request.put<ConfigUpdateResult, ApiResult<ConfigUpdateResult>>(
      CONFIG_URL.byId(configId),
      payload
    );
  },

  /** 带守卫的物理删除：内置参数（is_builtin）拒绝删除 */
  remove(configId: string) {
    return request.delete<null, ApiResult<null>>(CONFIG_URL.byId(configId));
  },
};
