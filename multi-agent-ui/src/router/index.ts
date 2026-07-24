import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import MainLayout from "@/layout/MainLayout.vue";
import Workspace from "@/views/Workspace.vue";
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
