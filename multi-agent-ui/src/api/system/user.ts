import request, { type ApiResult } from "@/utils/request";
import { USER_URL, type PageResult } from "./index";

/** 用户实体（对应后端 sys_user.to_dict，永不包含 password） */
export interface User {
  id: string;
  /** 登录用户名，全局唯一 */
  username: string;
  nickname: string | null;
  /** 所属部门 id，可为空 */
  dept_id: string | null;
  email: string | null;
  phone: string | null;
  avatar: string | null;
  status: string;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

/** 创建用户请求体（password 为明文，由服务端 bcrypt 哈希后存储） */
export interface UserCreatePayload {
  username: string;
  password: string;
  nickname?: string | null;
  dept_id?: string | null;
  email?: string | null;
  phone?: string | null;
  avatar?: string | null;
  status?: string;
  remark?: string | null;
}

/** 更新用户请求体（不含 password，密码变更走 resetPassword；dept_id 可显式置空） */
export interface UserUpdatePayload {
  username?: string;
  nickname?: string | null;
  email?: string | null;
  phone?: string | null;
  avatar?: string | null;
  status?: string;
  remark?: string | null;
  dept_id?: string | null;
}

/** 分页列出用户参数 */
export interface UserListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 按用户名/昵称模糊搜索 */
  keyword?: string;
  /** 按部门精确过滤 */
  dept_id?: string;
  /** 按状态精确过滤 */
  status?: string;
}

/** 用户管理 API：统一通过 userApi.xx() 调用 */
export const userApi = {
  /** 创建用户（username 全局唯一，响应不含 password） */
  create(payload: UserCreatePayload) {
    return request.post<User, ApiResult<User>>(USER_URL.root, payload);
  },

  /** 真分页列出用户，可选按关键词/部门/状态过滤 */
  list(params: UserListParams = {}) {
    return request.get<PageResult<User>, ApiResult<PageResult<User>>>(USER_URL.root, {
      params,
    });
  },

  /** 按 id 获取用户 */
  get(userId: string) {
    return request.get<User, ApiResult<User>>(USER_URL.byId(userId));
  },

  /** 更新用户基本信息（变更 username 时后端校验唯一，dept_id 可显式置空） */
  update(userId: string, payload: UserUpdatePayload) {
    return request.put<User, ApiResult<User>>(USER_URL.byId(userId), payload);
  },

  /** 重置用户密码（明文提交，服务端 bcrypt 哈希后覆盖） */
  resetPassword(userId: string, password: string) {
    return request.put<null, ApiResult<null>>(USER_URL.password(userId), { password });
  },

  /** 分配角色（全量覆盖语义：传空数组即清空） */
  assignRoles(userId: string, roleIds: string[]) {
    return request.put<null, ApiResult<null>>(USER_URL.roles(userId), { role_ids: roleIds });
  },

  /** 查询用户已分配的角色 id 列表（供分配弹窗回显） */
  listRoleIds(userId: string) {
    return request.get<string[], ApiResult<string[]>>(USER_URL.roles(userId));
  },

  /** 物理删除用户（后端同事务清理其角色关联） */
  remove(userId: string) {
    return request.delete<null, ApiResult<null>>(USER_URL.byId(userId));
  },
};
