/**
 * 用户登录态 store：token + 当前用户信息的唯一状态源。
 *
 * token 持久化于 localStorage（utils/auth.ts），store 初始化时恢复；
 * 登录/登出/查询当前用户均走 authApi，401 失效由 request 拦截器统一处理。
 */

import { defineStore } from "pinia";
import { ref } from "vue";
import { authApi, type User } from "@/api/system";
import { getToken, removeToken, setToken } from "@/utils/auth";

export const useUserStore = defineStore("user", () => {
  // 初始化时从 localStorage 恢复登录态
  const token = ref<string>(getToken());
  const userInfo = ref<User | null>(null);

  /** 用户名/密码登录：成功后写入 token 与用户信息 */
  async function login(username: string, password: string) {
    const res = await authApi.login({ username, password });
    token.value = res.data.token;
    userInfo.value = res.data.user;
    setToken(res.data.token);
  }

  /** 登出：通知服务端（失败不阻断），清除本地登录态 */
  async function logout() {
    try {
      await authApi.logout();
    } catch {
      // 无状态登出：服务端调用失败也照常清除本地状态
    }
    token.value = "";
    userInfo.value = null;
    removeToken();
  }

  /** 拉取当前 JWT 对应的用户信息（如刷新页面后恢复 userInfo） */
  async function fetchUserInfo() {
    const res = await authApi.me();
    userInfo.value = res.data;
    return res.data;
  }

  return { token, userInfo, login, logout, fetchUserInfo };
});
