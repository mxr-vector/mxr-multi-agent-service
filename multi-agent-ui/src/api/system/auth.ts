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

  /** 查询当前 JWT 对应的用户信息 */
  me() {
    return request.get<User, ApiResult<User>>(AUTH_URL.me);
  },
};
