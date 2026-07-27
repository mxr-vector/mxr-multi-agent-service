/**
 * 鉴权 token 工具：集中管理请求所需的 Bearer token。
 *
 * token 来源于登录接口签发的 JWT，持久化在 localStorage；
 * 由 userStore.login/logout 负责写入与清除，请求层经 getToken 读取注入。
 */

const TOKEN_KEY = "Authorization";

/** 获取鉴权 token（不含 Bearer 前缀），无值时返回空串 */
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

/** 写入鉴权 token（登录成功后调用） */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

/** 清除鉴权 token（登出或 401 失效时调用） */
export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}
