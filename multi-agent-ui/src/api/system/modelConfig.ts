import request, { type ApiResult } from "@/utils/request";
import { MODEL_CONFIG_URL } from "./index";

/** 模型配置实体（对应后端 sys_model_config.to_dict；api_key 为掩码值） */
export interface ModelConfig {
  id: string;
  /** 模型角色：chat / rewrite / visual / rerank，全局唯一，创建后不可变 */
  role: string;
  /** 卡片标题（中文名），如 '对话模型' */
  name: string;
  model_name: string;
  api_url: string;
  /** 掩码后的密钥（前 4 后 4，中间 ****）；编辑提交时留空则不修改 */
  api_key: string;
  /** provider 标识，目前仅 rerank 使用 */
  provider: string | null;
  /** 单请求超时（秒），目前 chat/visual 使用 */
  timeout: number | null;
  /** 失败重试次数，目前 chat/visual 使用 */
  max_retries: number | null;
  /** 角色特有参数兜底 */
  extra: Record<string, unknown> | null;
  /** 内置行删除保护标记，创建后不可变 */
  is_builtin: boolean;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

/** 更新模型配置请求体（role/is_builtin 不可变；api_key 留空或为掩码占位则不修改） */
export interface ModelConfigUpdatePayload {
  name?: string;
  model_name?: string;
  api_url?: string;
  /** 仅在需要更换密钥时提交完整明文；留空则保持原值 */
  api_key?: string;
  provider?: string | null;
  timeout?: number | null;
  max_retries?: number | null;
  extra?: Record<string, unknown> | null;
  remark?: string | null;
}

/** 更新返回体：在模型配置基础上附带热更新是否生效标识 */
export type ModelConfigUpdateResult = ModelConfig & { refreshed?: boolean };

/** 模型配置管理 API：统一通过 modelConfigApi.xx() 调用 */
export const modelConfigApi = {
  /** 全量列出模型配置（api_key 掩码），供卡片页渲染 */
  list() {
    return request.get<ModelConfig[], ApiResult<ModelConfig[]>>(MODEL_CONFIG_URL.root);
  },

  /** 按角色精确查询单个模型配置（api_key 掩码） */
  getByRole(role: string) {
    return request.get<ModelConfig, ApiResult<ModelConfig>>(MODEL_CONFIG_URL.byRole(role));
  },

  /** 原子更新单行模型配置；成功后端触发配置快照刷新，结果经 data.refreshed 透出 */
  update(configId: string, payload: ModelConfigUpdatePayload) {
    return request.put<ModelConfigUpdateResult, ApiResult<ModelConfigUpdateResult>>(
      MODEL_CONFIG_URL.byId(configId),
      payload
    );
  },
};
