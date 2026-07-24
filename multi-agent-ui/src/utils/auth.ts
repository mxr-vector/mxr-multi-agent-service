/**
 * 鉴权 token 工具：集中管理请求所需的 Bearer token。
 *
 * 当前 token 为静态密钥，来源于环境变量 VITE_APP_TOKEN（对应后端 API_SECRET_KEY）。
 * 后续若接入登录体系，可在此改为从 localStorage / userStore 读取动态用户 token。
 */

/** 获取鉴权 token（不含 Bearer 前缀），无值时返回空串 */
export function getToken(): string {
  return import.meta.env.VITE_APP_TOKEN ?? "";
}

/** 构造 Authorization 头部值：`Bearer <token>`，无 token 时返回空串 */
export function getAuthorization(): string {
  const token = getToken();
  return token ? `Bearer ${token}` : "";
}
