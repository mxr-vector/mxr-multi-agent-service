import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import MainLayout from "@/layout/MainLayout.vue";
import Workspace from "@/views/Workspace.vue";
import { getToken } from "@/utils/auth";
import { useMenuStore } from "@/stores/menuStore";
import { useUserStore } from "@/stores/userStore";
import { useDictStore } from "@/stores/dictStore";
import { navigationItems, type NavigationItem } from "./navigation";

// 自动扫描 @/views 下的页面组件（登录页除外），生成 组件键 -> 异步加载函数 映射；
// 键名规则：目录-文件（system/User.vue -> system-user），index.vue 取目录名（agents/index.vue -> agents），
// 非目录首页额外登记文件名短键（KnowledgeBase.vue -> knowledge-base），兼容后端菜单省略目录前缀的写法
const pageModules = import.meta.glob(["@/views/**/*.vue", "!@/views/login/**"]);

/** 归一化组件键：忽略大小写与 -/_ 差异，容忍后端菜单的不同命名风格 */
function normalizeViewKey(key: string) {
  return key.toLowerCase().replace(/[-_]/g, "");
}

// 归一化后的组件索引（knowledgebase / systemuser ...），供 resolveViewComponent 查找
const viewIndex = new Map<string, () => Promise<unknown>>();

for (const [file, loader] of Object.entries(pageModules)) {
  const segments = file
    .replace(/^.*\/views\//, "")
    .replace(/\.vue$/, "")
    .split("/");
  if (segments.at(-1)?.toLowerCase() === "index") segments.pop();
  if (!segments.length) continue;
  viewIndex.set(normalizeViewKey(segments.join("-")), loader);
  // 短键冲突时保留先登记者，避免不同目录的同名文件互相覆盖
  const shortKey = normalizeViewKey(segments.at(-1)!);
  if (!viewIndex.has(shortKey)) viewIndex.set(shortKey, loader);
}

// 无法由文件路径自然推导的历史组件键别名（后端菜单仍在使用）
const viewAliases: Record<string, string> = {
  agent: "agents", // 后端菜单写作单数，目录为复数 agents
  document: "rag-ducument", // 文件名拼写为 Ducument.vue，后端键为 document
};

for (const [alias, target] of Object.entries(viewAliases)) {
  const loader = viewIndex.get(normalizeViewKey(target));
  if (loader) viewIndex.set(normalizeViewKey(alias), loader);
}

/** 依次用 component 键、路由名、路径末段解析页面组件，均未命中回退 Workspace 占位页 */
function resolveViewComponent(item: NavigationItem): RouteRecordRaw["component"] {
  const candidates = [item.component, item.name, item.path.split("/").pop()];
  for (const candidate of candidates) {
    if (!candidate) continue;
    const loader = viewIndex.get(normalizeViewKey(candidate));
    if (loader) return loader as RouteRecordRaw["component"];
  }
  return Workspace;
}

/** 将导航项（静态或后端菜单转换结果）展开为 MainLayout 下的子路由记录 */
function createChildRoutes(items: readonly NavigationItem[]): RouteRecordRaw[] {
  return items.flatMap((item) => {
    if (item.children?.length) return createChildRoutes(item.children);
    // dir 目录仅作侧边栏分组，空目录不注册路由（否则会兜底渲染 Workspace 占位页）
    if (item.type === "dir") return [];
    return {
      path: item.path.slice(1),
      name: item.name,
      component: resolveViewComponent(item),
      meta: item,
      children: [],
    };
  });
}

// 静态路由仅含登录页与工作台/会话中心；其余路由登录后由后端菜单动态注册。
// 兜底重定向也随动态路由注册，避免刷新深链接时被提前劫持到 /overview。
const routes: RouteRecordRaw[] = [
  // 登录页脱离 MainLayout，独立全屏渲染
  { path: "/login", name: "login", component: () => import("@/views/login/Login.vue") },
  {
    path: "/",
    name: "layout",
    component: MainLayout,
    redirect: "/overview",
    children: createChildRoutes(navigationItems),
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

// 已注册动态路由的名称，登出时按名移除
let dynamicRouteNames: string[] = [];

/** 把后端菜单导航项注册为动态路由，并追加未匹配兜底重定向 */
export function registerDynamicRoutes(items: readonly NavigationItem[]) {
  createChildRoutes(items).forEach((record) => {
    router.addRoute("layout", record);
    dynamicRouteNames.push(record.name as string);
  });
  router.addRoute({ path: "/:pathMatch(.*)*", name: "not-found", redirect: "/overview" });
  dynamicRouteNames.push("not-found");
}

/** 移除全部动态路由（登出时调用，回到仅静态路由状态） */
export function resetDynamicRoutes() {
  dynamicRouteNames.forEach((name) => {
    if (router.hasRoute(name)) router.removeRoute(name);
  });
  dynamicRouteNames = [];
}

// 全局前置守卫：未登录一律送去 /login（记录来源用于登录后回跳）；已登录访问 /login 则送回首页；
// 首次导航时拉取后端路由菜单并注册动态路由，再按原始地址重进一次以命中新路由。
router.beforeEach(async (to) => {
  const hasToken = !!getToken();
  if (to.name === "login") {
    return hasToken ? { path: "/" } : true;
  }
  if (!hasToken) {
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  const menuStore = useMenuStore();
  if (!menuStore.loaded) {
    // 与菜单加载并行预热 data_scope（刷新后内存态丢失）：
    // 让依赖 dataScope 的页面（如 RAG 部门树 v-if）在挂载时即可同步判定，
    // 避免等 /auth/me 返回后才异步插入树造成的概率性闪现/布局跳动；
    // 失败不阻断导航（消费页仍会各自 ensureDataScope 重试）
    const dataScopeReady = useUserStore()
      .ensureDataScope()
      .catch(() => {});
    // 同模式并行预热全局词典（状态/可见性等下拉与标签文案数据源），
    // 失败不阻断导航（组件侧 getLabel/getOptions 有原值回退）
    const dictReady = useDictStore()
      .ensureLoaded()
      .catch(() => {});
    await menuStore.loadMenus();
    registerDynamicRoutes(menuStore.dynamicItems);
    await dataScopeReady;
    await dictReady;
    return { path: to.path, query: to.query, hash: to.hash, replace: true };
  }
  return true;
});
