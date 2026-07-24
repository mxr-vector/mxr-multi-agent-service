import axios, { type InternalAxiosRequestConfig, type AxiosResponse } from "axios";
import { ElMessage, ElMessageBox } from "element-plus";
import errorCode from "@/utils/errorCode";
import { getToken } from "@/utils/auth";

// 后端统一响应结构：所有接口经响应拦截器后返回 { code, msg, data }
export interface ApiResult<T = unknown> {
  code: number;
  msg: string;
  data: T;
}

// 是否显示重新登录提示，避免 401 时重复弹窗
export const isRelogin: { show: boolean } = { show: false };

// 创建 axios 实例
const service = axios.create({
  // baseURL 使用代理前缀（如 /dev-api），经 Vite proxy 转发并剥离前缀
  baseURL: import.meta.env.VITE_APP_BASE_API,
  timeout: 15000,
  headers: { "Content-Type": "application/json;charset=utf-8" },
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
      if (!isRelogin.show) {
        isRelogin.show = true;
        ElMessageBox.confirm("登录状态已过期，您可以继续留在该页面，或者重新登录", "系统提示", {
          confirmButtonText: "重新登录",
          cancelButtonText: "取消",
          type: "warning",
        })
          .then(() => {
            isRelogin.show = false;
            location.href = "/";
          })
          .catch(() => {
            isRelogin.show = false;
          });
      }
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
    // 对响应错误做点什么
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
