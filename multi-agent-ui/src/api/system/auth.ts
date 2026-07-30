import request, { type ApiResult } from "@/utils/request";
import { AUTH_URL } from "./index";
import type { User } from "./user";

/** 登录请求体（明文密码，服务端 bcrypt 校验） */
export interface LoginPayload {
  username: string;
  password: string;
}

/** 登录响应载荷：JWT token + 用户基础信息（不含 password） */
export interface LoginResult {
  token: string;
  user: User;
}

/** 数据权限档位（sys_role.data_scope，聚合取最宽档） */
export type DataScope = "all" | "dept_and_child" | "dept" | "self";

/** /auth/me 响应：用户基础信息 + 聚合 data_scope（登录响应不含该字段） */
export type CurrentUser = User & { data_scope: DataScope };

/** 个人资料更新请求体（仅本人可维护字段，username/status 等管理字段不开放） */
export interface ProfileUpdatePayload {
  nickname?: string | null;
  email?: string | null;
  phone?: string | null;
  avatar?: string | null;
}

/** 认证 API：统一通过 authApi.xx() 调用 */
export const authApi = {
  /** 用户名/密码登录（免鉴权接口，成功返回 JWT 与用户信息） */
  login(payload: LoginPayload) {
    return request.post<LoginResult, ApiResult<LoginResult>>(AUTH_URL.login, payload);
  },

  /** 登出（无状态语义：服务端不吊销 token，前端负责清除本地 token） */
  logout() {
    return request.post<null, ApiResult<null>>(AUTH_URL.logout);
  },

  /** 查询当前 JWT 对应的用户信息（附聚合 data_scope） */
  me() {
    return request.get<CurrentUser, ApiResult<CurrentUser>>(AUTH_URL.me);
  },

  /** 更新当前用户个人资料（昵称/邮箱/手机/头像），返回更新后的用户信息 */
  updateProfile(payload: ProfileUpdatePayload) {
    return request.put<User, ApiResult<User>>(AUTH_URL.me, payload);
  },

  /** 修改自己密码（服务端先校验原密码，再 bcrypt 哈希新密码覆盖） */
  changePassword(oldPassword: string, newPassword: string) {
    return request.put<null, ApiResult<null>>(AUTH_URL.password, {
      old_password: oldPassword,
      new_password: newPassword,
    });
  },

  /** 上传当前用户头像（multipart，图片 2MB 以内），返回更新后的用户信息 */
  uploadAvatar(file: File) {
    const form = new FormData();
    form.append("file", file);
    return request.post<User, ApiResult<User>>(AUTH_URL.avatar, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
};

/** 头像地址解析：后端存相对路径（/public/files/...）时补代理前缀，绝对地址原样返回 */
export function resolveAvatarUrl(avatar: string | null | undefined): string {
  if (!avatar) return "";
  if (/^(https?:)?\/\//.test(avatar) || avatar.startsWith("data:")) return avatar;
  return import.meta.env.VITE_APP_BASE_API + avatar;
}
