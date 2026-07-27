import request, { type ApiResult } from "@/utils/request";
import { ROLE_URL, type PageResult } from "./index";

/** 角色实体（对应后端 sys_role.to_dict） */
export interface Role {
  id: string;
  name: string;
  /** 角色标识（如 'admin'），全局唯一 */
  role_key: string;
  /** 数据权限范围（本阶段仅数据标记） */
  data_scope: string;
  sort_order: number;
  status: string;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

/** 创建角色请求体（role_key 全局唯一） */
export interface RoleCreatePayload {
  name: string;
  role_key: string;
  data_scope?: string;
  sort_order?: number;
  status?: string;
  remark?: string | null;
}

/** 更新角色请求体（仅提供的字段会被更新） */
export interface RoleUpdatePayload {
  name?: string;
  role_key?: string;
  data_scope?: string;
  sort_order?: number;
  status?: string;
  remark?: string | null;
}

/** 分页列出角色参数 */
export interface RoleListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按名称/角色标识模糊搜索 */
  keyword?: string;
  /** 按状态精确过滤 */
  status?: string;
}

/** 角色管理 API：统一通过 roleApi.xx() 调用 */
export const roleApi = {
  /** 创建角色（role_key 全局唯一） */
  create(payload: RoleCreatePayload) {
    return request.post<Role, ApiResult<Role>>(ROLE_URL.root, payload);
  },

  /** 真分页列出角色（sort_order 升序），可选按关键词/状态过滤 */
  list(params: RoleListParams = {}) {
    return request.get<PageResult<Role>, ApiResult<PageResult<Role>>>(ROLE_URL.root, {
      params,
    });
  },

  /** 按 id 获取角色 */
  get(roleId: string) {
    return request.get<Role, ApiResult<Role>>(ROLE_URL.byId(roleId));
  },

  /** 更新角色（变更 role_key 时后端校验唯一） */
  update(roleId: string, payload: RoleUpdatePayload) {
    return request.put<Role, ApiResult<Role>>(ROLE_URL.byId(roleId), payload);
  },

  /** 分配菜单（全量覆盖语义：传空数组即清空） */
  assignMenus(roleId: string, menuIds: string[]) {
    return request.put<null, ApiResult<null>>(ROLE_URL.menus(roleId), { menu_ids: menuIds });
  },

  /** 查询角色已绑定的菜单 id 列表（供分配弹窗树勾选回显） */
  listMenuIds(roleId: string) {
    return request.get<string[], ApiResult<string[]>>(ROLE_URL.menus(roleId));
  },

  /** 带守卫的物理删除：角色已分配给用户时拒绝删除 */
  remove(roleId: string) {
    return request.delete<null, ApiResult<null>>(ROLE_URL.byId(roleId));
  },
};
