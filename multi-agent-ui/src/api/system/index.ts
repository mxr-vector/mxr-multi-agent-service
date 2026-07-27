/**
 * 系统管理模块后端接口地址维护中心。
 *
 * request 实例的 baseURL 为 VITE_APP_BASE_API（如 /dev-api），经 Vite 代理转发时会剥离该前缀，
 * 代理目标已含服务端父路由前缀（ENV.base_url），因此这里只需写 /system 起始的路径。
 *
 * 所有系统管理功能函数统一从各子模块导入这里维护的 URL，避免地址散落各处。
 */

/** 系统管理模块统一前缀（对应后端 routers/system/ 各 router 的 /system 前缀） */
const BASE = "/system";

/**
 * 统一分页结果契约（对应后端 utils/page.py::PageResult）。
 *
 * items 为当前页数据，total 为过滤后的总量，pages 为总页数；
 * 作为统一响应 ApiResult 的 data 载荷返回。
 */
export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

/** 字典类型管理接口地址 */
export const DICT_TYPE_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/dict-types`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/dict-types/${id}`,
} as const;

/** 字典数据管理接口地址 */
export const DICT_DATA_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/dict-data`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/dict-data/${id}`,
  /** 按类型键取全量字典项（下拉框数据源） */
  byType: (dictType: string) => `${BASE}/dict-data/type/${dictType}`,
} as const;

/** 参数配置管理接口地址 */
export const CONFIG_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/configs`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/configs/${id}`,
  /** 按 key 精确查询 */
  byKey: (key: string) => `${BASE}/configs/key/${key}`,
} as const;

/** 部门管理接口地址 */
export const DEPT_URL = {
  /** 扁平列表 / 新建 */
  root: `${BASE}/depts`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/depts/${id}`,
} as const;

/** 用户管理接口地址 */
export const USER_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/users`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/users/${id}`,
  /** 重置密码 */
  password: (id: string) => `${BASE}/users/${id}/password`,
  /** 分配角色（PUT 全量覆盖）/ 查询已分配角色 id（GET 回显） */
  roles: (id: string) => `${BASE}/users/${id}/roles`,
} as const;

/** 角色管理接口地址 */
export const ROLE_URL = {
  /** 列表 / 新建 */
  root: `${BASE}/roles`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/roles/${id}`,
  /** 分配菜单（PUT 全量覆盖）/ 查询已绑定菜单 id（GET 回显） */
  menus: (id: string) => `${BASE}/roles/${id}/menus`,
} as const;

/** 菜单管理接口地址 */
export const MENU_URL = {
  /** 扁平列表 / 新建 */
  root: `${BASE}/menus`,
  /** 详情 / 更新 / 删除 */
  byId: (id: string) => `${BASE}/menus/${id}`,
} as const;

/** 认证接口地址（登录挂 /public 下免鉴权，其余走 JWT 通道） */
export const AUTH_URL = {
  /** 用户名/密码登录（免鉴权） */
  login: "/public/auth/login",
  /** 登出（无状态语义） */
  logout: "/auth/logout",
  /** 当前用户信息 */
  me: "/auth/me",
} as const;

// 统一出口：业务侧可直接从 "@/api/system" 导入 xxApi 对象与类型
export * from "./auth";
export * from "./dict";
export * from "./config";
export * from "./dept";
export * from "./user";
export * from "./role";
export * from "./menu";
