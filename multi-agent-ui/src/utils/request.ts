import axios, { type InternalAxiosRequestConfig, type AxiosResponse } from "axios";
import { ElMessage } from "element-plus";
import errorCode from "@/utils/errorCode";
import { getToken, removeToken } from "@/utils/auth";

// 后端统一响应结构：所有接口经响应拦截器后返回 { code, msg, data }
export interface ApiResult<T = unknown> {
  code: number;
  msg: string;
  data: T;
}

// 是否已在处理 401 跳转，避免并发请求重复清 token / 重复跳转
export const isRelogin: { show: boolean } = { show: false };

/** 登录态失效统一出口：清除本地 token 并携带来源页跳转登录页 */
function redirectToLogin() {
  if (isRelogin.show) return;
  isRelogin.show = true;
  removeToken();
  const redirect = location.pathname + location.search;
  const query =
    redirect && redirect !== "/login" ? `?redirect=${encodeURIComponent(redirect)}` : "";
  location.href = `/login${query}`;
}

// 创建 axios 实例
const service = axios.create({
  // baseURL 使用代理前缀（如 /dev-api），经 Vite proxy 转发并剥离前缀
  baseURL: import.meta.env.VITE_APP_BASE_API,
  timeout: 15000,
  headers: { "Content-Type": "application/json;charset=utf-8" },
  // 数组查询参数序列化为重复键（dept_ids=a&dept_ids=b），匹配 FastAPI 多值 Query
  paramsSerializer: { indexes: null },
});

// 请求拦截器
service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 注入鉴权 token：后端 TokenAuthMiddleware 要求 Authorization: Bearer <API_SECRET_KEY>
    const token = getToken();
    if (token && !config.headers?.Authorization) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    // 对请求错误做些什么
    return Promise.reject(error);
  }
);

// 响应拦截器
service.interceptors.response.use(
  (res: AxiosResponse) => {
    // 未设置状态码则默认成功状态
    const code: number = res.data.code || 200;
    // 获取错误信息
    const msg: string = errorCode[code] || res.data.msg || errorCode["default"];
    // 二进制数据（文件下载等）直接返回
    if (res.config.responseType === "blob" || res.config.responseType === "arraybuffer") {
      return res.data;
    }
    if (code === 401) {
      // 业务体 401：登录态失效，清 token 并跳登录页
      redirectToLogin();
      return Promise.reject("无效的会话，或者会话已过期，请重新登录。");
    } else if (code === 500 || code === 601 || code !== 200) {
      ElMessage({
        message: msg,
        type: code === 601 ? "warning" : "error",
      });
      return Promise.reject(code === 500 ? new Error(msg) : "error");
    }
    return Promise.resolve(res.data);
  },
  (error) => {
    // 真实 HTTP 401（TokenAuthMiddleware 拒绝）：清 token 并跳登录页
    if (error.response?.status === 401) {
      redirectToLogin();
      return Promise.reject(error);
    }
    let { message } = error;
    if (message === "Network Error") {
      message = "后端接口连接异常";
    } else if (message.includes("timeout")) {
      message = "系统接口请求超时";
    } else if (message.includes("Request failed with status code")) {
      message = "系统接口" + message.slice(-3) + "异常";
    }
    ElMessage({ message, type: "error", duration: 5 * 1000 });
    return Promise.reject(error);
  }
);

export default service;
