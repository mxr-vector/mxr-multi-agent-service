/**
 * 用户登录态 store：token + 当前用户信息的唯一状态源。
 *
 * token 持久化于 localStorage（utils/auth.ts），store 初始化时恢复；
 * 登录/登出/查询当前用户均走 authApi，401 失效由 request 拦截器统一处理。
 */

import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { authApi, type DataScope, type User } from "@/api/system";
import { getToken, removeToken, setToken } from "@/utils/auth";
import { resetDynamicRoutes } from "@/router";
import { useMenuStore } from "@/stores/menuStore";
import { useDictStore } from "@/stores/dictStore";

/** 本地用户信息：登录响应不含 data_scope，由 /auth/me 懒补齐 */
type StoredUser = User & { data_scope?: DataScope };

export const useUserStore = defineStore("user", () => {
  // 初始化时从 localStorage 恢复登录态
  const token = ref<string>(getToken());
  const userInfo = ref<StoredUser | null>(null);

  /** 当前用户数据权限档位（未加载时为 undefined，消费方先 ensureDataScope） */
  const dataScope = computed<DataScope | undefined>(() => userInfo.value?.data_scope);

  /** 用户名/密码登录：成功后写入 token 与用户信息 */
  async function login(username: string, password: string) {
    const res = await authApi.login({ username, password });
    token.value = res.data.token;
    userInfo.value = res.data.user;
    setToken(res.data.token);
  }

  /** 登出：通知服务端（失败不阻断），清除本地登录态与动态路由菜单 */
  async function logout() {
    try {
      await authApi.logout();
    } catch {
      // 无状态登出：服务端调用失败也照常清除本地状态
    }
    token.value = "";
    userInfo.value = null;
    removeToken();
    // 清空动态菜单、全局词典并移除已注册的动态路由，下次登录重新拉取
    useMenuStore().reset();
    useDictStore().reset();
    resetDynamicRoutes();
  }

  /** 拉取当前 JWT 对应的用户信息（如刷新页面后恢复 userInfo，附 data_scope） */
  async function fetchUserInfo() {
    const res = await authApi.me();
    userInfo.value = res.data;
    return res.data;
  }

  /** ensureDataScope 的在途请求：并发调用共享同一次 /auth/me（单飞去重） */
  let dataScopePromise: Promise<DataScope> | null = null;

  /** 确保 data_scope 已加载（登录响应不含该字段，缺失时懒拉 /auth/me） */
  async function ensureDataScope(): Promise<DataScope> {
    if (userInfo.value?.data_scope) return userInfo.value.data_scope;
    if (!dataScopePromise) {
      dataScopePromise = fetchUserInfo()
        .then((user) => user.data_scope)
        .finally(() => {
          // 成功后走缓存分支；失败允许下次重试
          dataScopePromise = null;
        });
    }
    return dataScopePromise;
  }

  return { token, userInfo, dataScope, login, logout, fetchUserInfo, ensureDataScope };
});
