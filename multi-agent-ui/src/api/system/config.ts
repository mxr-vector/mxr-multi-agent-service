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

  /** 按 key 精确查询参数（供业务读取配置值） */
  getByKey(key: string) {
    return request.get<Config, ApiResult<Config>>(CONFIG_URL.byKey(key));
  },

  /** 更新参数配置（is_builtin 不可变，变更 key 时后端校验唯一） */
  update(configId: string, payload: ConfigUpdatePayload) {
    return request.put<Config, ApiResult<Config>>(CONFIG_URL.byId(configId), payload);
  },

  /** 带守卫的物理删除：内置参数（is_builtin）拒绝删除 */
  remove(configId: string) {
    return request.delete<null, ApiResult<null>>(CONFIG_URL.byId(configId));
  },
};
