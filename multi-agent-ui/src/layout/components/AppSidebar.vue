<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { navigationItems, type NavigationItem } from "@/router/navigation";
import { useMenuStore } from "@/stores/menuStore";
import NavIcon from "@/layout/components/NavIcon.vue";

interface Props {
  collapsed: boolean;
}
const props = defineProps<Props>();
const route = useRoute();
const menuStore = useMenuStore();
const expandedItemNames = ref<string[]>(["rag"]);

// 静态导航（工作台）在前，后端路由菜单接口返回的动态菜单在后
const items = computed<readonly NavigationItem[]>(() => [
  ...navigationItems,
  ...menuStore.dynamicItems,
]);

function isExpanded(name: string) {
  return expandedItemNames.value.includes(name);
}
function toggleChildren(name: string) {
  expandedItemNames.value = isExpanded(name)
    ? expandedItemNames.value.filter((itemName) => itemName !== name)
    : [...expandedItemNames.value, name];
}
function hasActiveChild(path: string) {
  return route.path.startsWith(`${path}/`);
}

/** dir 目录节点始终按父级分组渲染（空目录展开为空，不产生可点击页面） */
function isParent(item: NavigationItem) {
  return item.type === "dir" || Boolean(item.children?.length);
}
</script>

<template>
  <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': props.collapsed }">
    <RouterLink class="brand" to="/overview" aria-label="多智能体测试平台首页">
      <span class="brand-mark" aria-hidden="true">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.7"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M12 3 4 6.5v6c0 4.4 3.4 7.6 8 8.5 4.6-.9 8-4.1 8-8.5v-6L12 3Z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      </span>
      <span class="brand-copy">
        <strong>多智能体测试平台</strong>
        <small>Multi-Agent Platform</small>
      </span>
    </RouterLink>

    <nav class="navigation" aria-label="主导航">
      <template v-for="item in items" :key="item.name">
        <div v-if="isParent(item)" class="navigation-parent">
          <button
            class="navigation-link navigation-parent-trigger"
            :class="{ 'navigation-link--active': hasActiveChild(item.path) }"
            type="button"
            :title="props.collapsed ? item.label : undefined"
            :aria-expanded="isExpanded(item.name)"
            @click="toggleChildren(item.name)"
          >
            <span class="navigation-indicator" aria-hidden="true"></span>
            <span class="navigation-icon" aria-hidden="true">
              <NavIcon :icon="item.icon" :size="20" />
            </span>
            <span class="navigation-text">{{ item.label }}</span>
            <span class="navigation-chevron" aria-hidden="true">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="m6 9 6 6 6-6" />
              </svg>
            </span>
          </button>
          <div v-show="isExpanded(item.name) && !props.collapsed" class="navigation-children">
            <RouterLink
              v-for="child in item.children"
              :key="child.name"
              :to="child.path"
              class="navigation-child-link"
            >
              <span class="navigation-child-icon" aria-hidden="true">
                <NavIcon :icon="child.icon" :size="16" />
              </span>
              {{ child.label }}
            </RouterLink>
          </div>
        </div>
        <RouterLink
          v-else
          :to="item.path"
          class="navigation-link"
          :title="props.collapsed ? item.label : undefined"
        >
          <span class="navigation-indicator" aria-hidden="true"></span>
          <span class="navigation-icon" aria-hidden="true">
            <NavIcon :icon="item.icon" :size="20" />
          </span>
          <span class="navigation-text">{{ item.label }}</span>
        </RouterLink>
      </template>
    </nav>

    <div
      class="sidebar-status"
      :title="props.collapsed ? '系统运行中' : undefined"
      aria-label="系统运行状态：运行中"
    >
      <span class="sidebar-status-dot" aria-hidden="true"></span>
      <span class="sidebar-status-copy">
        <strong>系统运行中</strong>
        <small>所有服务正常</small>
      </span>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: sticky;
  top: 0;
  display: flex;
  height: 100vh;
  flex-direction: column;
  overflow: hidden;
  padding: 20px 14px 16px;
  color: #4a5675;
  background: #fff;
  border-right: 1px solid #e9edf5;
  transition: padding 180ms ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
  margin-bottom: 14px;
  padding: 4px 8px 18px;
  border-bottom: 1px solid #f0f2f9;
  color: inherit;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 12px;
  color: #fff;
  background: linear-gradient(135deg, #5b8bff, #6c63ff);
  box-shadow:
    0 6px 18px rgb(91 139 255 / 35%),
    inset 0 0 0 1px rgb(255 255 255 / 25%);
}

.brand-mark svg {
  width: 21px;
  height: 21px;
}

.brand-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
  white-space: nowrap;
}

.brand-copy strong {
  color: #1b2337;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.2px;
}

.brand-copy small {
  color: #9aa4bd;
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.6px;
  text-transform: uppercase;
}

.navigation {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  overflow-y: auto;
  padding-top: 2px;
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
}

.navigation:hover {
  scrollbar-color: #dfe4f0 transparent;
}

.navigation::-webkit-scrollbar {
  width: 4px;
}

.navigation::-webkit-scrollbar-thumb {
  border-radius: 4px;
  background: transparent;
}

.navigation:hover::-webkit-scrollbar-thumb {
  background: #dfe4f0;
}

.navigation-link {
  position: relative;
  display: flex;
  width: 100%;
  align-items: center;
  gap: 12px;
  min-height: 44px;
  padding: 0 12px;
  border: 0;
  border-radius: 11px;
  color: #5b6580;
  background: transparent;
  font-size: 14px;
  font-weight: 500;
  text-align: left;
  text-decoration: none;
  transition:
    background-color 150ms ease,
    color 150ms ease,
    box-shadow 150ms ease;
}

.navigation-link:hover {
  color: #2b3654;
  background: #f4f6fd;
}

.navigation-link.router-link-active,
.navigation-link--active {
  color: #4c6ef5;
  background: linear-gradient(90deg, #eef1ff 0%, #f6f3ff 100%);
  box-shadow: inset 0 0 0 1px rgb(76 110 245 / 8%);
  font-weight: 600;
}

.navigation-parent-trigger[aria-expanded="true"] {
  color: #2b3654;
}

/* 激活指示条：品牌渐变，与 logo / 工作台数字同一种视觉语言 */
.navigation-indicator {
  position: absolute;
  top: 50%;
  left: 0;
  width: 3px;
  height: 18px;
  border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, #5b8bff, #7c5cff);
  box-shadow: 0 0 10px rgb(92 107 255 / 45%);
  transform: translateY(-50%) scaleY(0);
  transition: transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
}

.navigation-link.router-link-active .navigation-indicator,
.navigation-link--active .navigation-indicator {
  transform: translateY(-50%) scaleY(1);
}

.navigation-chevron {
  display: grid;
  margin-left: auto;
  place-items: center;
  color: #a6afc6;
  transition: transform 180ms ease;
}

.navigation-chevron svg {
  width: 16px;
  height: 16px;
}

.navigation-parent-trigger[aria-expanded="true"] .navigation-chevron {
  transform: rotate(180deg);
}

.navigation-children {
  display: grid;
  gap: 2px;
  margin: 3px 0 6px 26px;
  padding-left: 12px;
  border-left: 1.5px solid #eef1f8;
}

.navigation-child-link {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 36px;
  padding: 0 10px;
  border-radius: 9px;
  color: #7b86a3;
  font-size: 13px;
  text-decoration: none;
  transition:
    background-color 150ms ease,
    color 150ms ease;
}

.navigation-child-link:hover {
  color: #2b3654;
  background: #f4f6fd;
}

.navigation-child-link.router-link-active {
  color: #4c6ef5;
  background: #f2f5ff;
  font-weight: 600;
}

.navigation-child-icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  color: currentcolor;
  opacity: 0.7;
}

.navigation-child-link.router-link-active .navigation-child-icon {
  opacity: 1;
}

.navigation-icon {
  display: grid;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  place-items: center;
  color: currentcolor;
}

.navigation-icon :deep(svg) {
  width: 20px;
  height: 20px;
}

.navigation-text {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 底部系统状态 */
.sidebar-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid #edf1f8;
  border-radius: 12px;
  background: linear-gradient(120deg, #f8faff 0%, #f5f7fd 100%);
}

.sidebar-status-dot {
  position: relative;
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #2fbf8f;
}

.sidebar-status-dot::after {
  content: "";
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: rgb(47 191 143 / 25%);
  animation: status-pulse 2.4s ease-out infinite;
}

@keyframes status-pulse {
  0% {
    transform: scale(0.5);
    opacity: 1;
  }

  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}

.sidebar-status-copy {
  display: grid;
  gap: 1px;
}

.sidebar-status-copy strong {
  color: #3a4562;
  font-size: 12px;
  font-weight: 600;
}

.sidebar-status-copy small {
  color: #9aa4bd;
  font-size: 10px;
}

/* 折叠态 */
.app-sidebar--collapsed {
  padding-right: 12px;
  padding-left: 12px;
}

.app-sidebar--collapsed .brand {
  justify-content: center;
  padding-right: 0;
  padding-left: 0;
}

.app-sidebar--collapsed .brand-copy,
.app-sidebar--collapsed .navigation-text,
.app-sidebar--collapsed .navigation-chevron,
.app-sidebar--collapsed .navigation-children,
.app-sidebar--collapsed .navigation-indicator {
  display: none;
}

.app-sidebar--collapsed .navigation-link {
  justify-content: center;
  padding: 0;
}

.app-sidebar--collapsed .navigation-link.router-link-active,
.app-sidebar--collapsed .navigation-link--active {
  color: #fff;
  background: linear-gradient(135deg, #5b8bff, #6c63ff);
  box-shadow: 0 6px 16px rgb(92 107 255 / 40%);
}

.app-sidebar--collapsed .sidebar-status {
  justify-content: center;
  padding: 10px 0;
  border-color: transparent;
  background: transparent;
}

.app-sidebar--collapsed .sidebar-status-copy {
  display: none;
}

@media (prefers-reduced-motion: reduce) {
  .sidebar-status-dot::after {
    animation: none;
  }
}
</style>
