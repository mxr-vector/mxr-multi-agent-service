import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import MainLayout from "@/layout/MainLayout.vue";
import Workspace from "@/views/Workspace.vue";
import { getToken } from "@/utils/auth";
import { navigationItems } from "./navigation";

// 导航名 -> 页面组件（每个菜单目标对应 views/ 下独立维护的页面）
const viewModules = {
  overview: () => import("@/views/overview/index.vue"),
  conversations: () => import("@/views/conversations/index.vue"),
  workflows: () => import("@/views/workflows/index.vue"),
  agents: () => import("@/views/agents/index.vue"),
  settings: () => import("@/views/settings/index.vue"),
  "rag-knowledge-base": () => import("@/views/rag/KnowledgeBase.vue"),
  "rag-ducument": () => import("@/views/rag/Ducument.vue"),
  "system-user": () => import("@/views/system/User.vue"),
  "system-role": () => import("@/views/system/Role.vue"),
  "system-menu": () => import("@/views/system/Menu.vue"),
  "system-dept": () => import("@/views/system/Dept.vue"),
  "system-dict": () => import("@/views/system/Dict.vue"),
  "system-config": () => import("@/views/system/Config.vue"),
};

function createChildRoutes(items = navigationItems): RouteRecordRaw[] {
  return items.flatMap((item) => {
    if (item.children?.length) return createChildRoutes(item.children);
    return {
      path: item.path.slice(1),
      name: item.name,
      component: viewModules[item.name as keyof typeof viewModules] ?? Workspace,
      meta: item,
      children: [],
    };
  });
}

const routes: RouteRecordRaw[] = [
  // 登录页脱离 MainLayout，独立全屏渲染
  { path: "/login", name: "login", component: () => import("@/views/login/Login.vue") },
  {
    path: "/",
    component: MainLayout,
    redirect: "/overview",
    children: createChildRoutes(),
  },
  { path: "/:pathMatch(.*)*", redirect: "/overview" },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

// 全局前置守卫：未登录一律送去 /login（记录来源用于登录后回跳）；已登录访问 /login 则送回首页
router.beforeEach((to) => {
  const hasToken = !!getToken();
  if (to.name === "login") {
    return hasToken ? { path: "/" } : true;
  }
  if (!hasToken) {
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  return true;
});
