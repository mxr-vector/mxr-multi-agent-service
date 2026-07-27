import request, { type ApiResult } from "@/utils/request";
import { DICT_TYPE_URL, DICT_DATA_URL, type PageResult } from "./index";

/** 字典类型实体（对应后端 sys_dict_type.to_dict） */
export interface DictType {
  id: string;
  name: string;
  /** 字典类型键（如 'sys_sex'），全局唯一，字典数据以此逻辑关联 */
  type: string;
  status: string;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

/** 字典数据实体（对应后端 sys_dict_data.to_dict） */
export interface DictData {
  id: string;
  /** 所属字典类型键，创建后不可变 */
  dict_type: string;
  label: string;
  value: string;
  sort_order: number;
  is_default: boolean;
  status: string;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

/** 创建字典类型请求体（type 键全局唯一） */
export interface DictTypeCreatePayload {
  name: string;
  type: string;
  status?: string;
  remark?: string | null;
}

/** 更新字典类型请求体（仅提供的字段会被更新，改 type 键会级联更新字典数据） */
export interface DictTypeUpdatePayload {
  name?: string;
  type?: string;
  status?: string;
  remark?: string | null;
}

/** 分页列出字典类型参数 */
export interface DictTypeListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按名称/类型键模糊搜索 */
  keyword?: string;
  /** 按状态精确过滤 */
  status?: string;
}

/** 创建字典数据请求体（dict_type 必须指向已存在的类型键） */
export interface DictDataCreatePayload {
  dict_type: string;
  label: string;
  value: string;
  sort_order?: number;
  is_default?: boolean;
  status?: string;
  remark?: string | null;
}

/** 更新字典数据请求体（仅提供的字段会被更新，dict_type 创建后不可变） */
export interface DictDataUpdatePayload {
  label?: string;
  value?: string;
  sort_order?: number;
  is_default?: boolean;
  status?: string;
  remark?: string | null;
}

/** 分页列出字典数据参数 */
export interface DictDataListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按类型键精确过滤 */
  dict_type?: string;
  /** 按标签模糊搜索 */
  keyword?: string;
  /** 按状态精确过滤 */
  status?: string;
}

/** 字典类型管理 API：统一通过 dictTypeApi.xx() 调用 */
export const dictTypeApi = {
  /** 创建字典类型（type 键全局唯一） */
  create(payload: DictTypeCreatePayload) {
    return request.post<DictType, ApiResult<DictType>>(DICT_TYPE_URL.root, payload);
  },

  /** 真分页列出字典类型，可选按关键词/状态过滤 */
  list(params: DictTypeListParams = {}) {
    return request.get<PageResult<DictType>, ApiResult<PageResult<DictType>>>(DICT_TYPE_URL.root, {
      params,
    });
  },

  /** 按 id 获取字典类型 */
  get(dictTypeId: string) {
    return request.get<DictType, ApiResult<DictType>>(DICT_TYPE_URL.byId(dictTypeId));
  },

  /** 更新字典类型；变更 type 键时后端同事务级联更新其下字典数据 */
  update(dictTypeId: string, payload: DictTypeUpdatePayload) {
    return request.put<DictType, ApiResult<DictType>>(DICT_TYPE_URL.byId(dictTypeId), payload);
  },

  /** 带守卫的物理删除：类型下仍有字典数据时拒绝删除 */
  remove(dictTypeId: string) {
    return request.delete<null, ApiResult<null>>(DICT_TYPE_URL.byId(dictTypeId));
  },
};

/** 字典数据管理 API：统一通过 dictDataApi.xx() 调用 */
export const dictDataApi = {
  /** 创建字典数据（dict_type 必须已存在） */
  create(payload: DictDataCreatePayload) {
    return request.post<DictData, ApiResult<DictData>>(DICT_DATA_URL.root, payload);
  },

  /** 真分页列出字典数据（sort_order 升序），可选按类型键/关键词/状态过滤 */
  list(params: DictDataListParams = {}) {
    return request.get<PageResult<DictData>, ApiResult<PageResult<DictData>>>(DICT_DATA_URL.root, {
      params,
    });
  },

  /** 按类型键取全量字典项（sort_order 升序），供下拉框消费 */
  listByType(dictType: string) {
    return request.get<DictData[], ApiResult<DictData[]>>(DICT_DATA_URL.byType(dictType));
  },

  /** 按 id 获取字典数据 */
  get(dictDataId: string) {
    return request.get<DictData, ApiResult<DictData>>(DICT_DATA_URL.byId(dictDataId));
  },

  /** 更新字典数据（dict_type 创建后不可变） */
  update(dictDataId: string, payload: DictDataUpdatePayload) {
    return request.put<DictData, ApiResult<DictData>>(DICT_DATA_URL.byId(dictDataId), payload);
  },

  /** 物理删除字典数据 */
  remove(dictDataId: string) {
    return request.delete<null, ApiResult<null>>(DICT_DATA_URL.byId(dictDataId));
  },
};
