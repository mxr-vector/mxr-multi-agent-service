import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import MainLayout from '@/layout/MainLayout.vue'
import Workspace from '@/views/Workspace.vue'
import { navigationItems } from './navigation'

const ragViews = {
  'rag-knowledge-base': () => import('@/views/rag/KnowledgeBase.vue'),
  'rag-ducument': () => import('@/views/rag/Ducument.vue'),
  'rag-categories': () => import('@/views/rag/Categories.vue'),
}

function createChildRoutes(items = navigationItems): RouteRecordRaw[] {
  return items.flatMap((item) => {
    if (item.children?.length) return createChildRoutes(item.children)
    return {
      path: item.path.slice(1),
      name: item.name,
      component: ragViews[item.name as keyof typeof ragViews] ?? Workspace,
      meta: item,
      children: [],
    }
  })
}

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: MainLayout,
    redirect: '/overview',
    children: createChildRoutes(),
  },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})