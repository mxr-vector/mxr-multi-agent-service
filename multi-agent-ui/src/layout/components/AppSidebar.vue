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
        <small>Multi-Agent Test Platform</small>
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
          <span class="navigation-icon" aria-hidden="true">
            <NavIcon :icon="item.icon" :size="20" />
          </span>
          <span class="navigation-text">{{ item.label }}</span>
        </RouterLink>
      </template>
    </nav>
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
  padding: 20px 16px 18px;
  color: #4a5675;
  background: linear-gradient(180deg, #ffffff 0%, #f4f7ff 100%);
  border-right: 1px solid #eef1f8;
  transition: padding 180ms ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
  padding: 4px 8px 22px;
  color: inherit;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 12px;
  color: #fff;
  background: linear-gradient(135deg, #5b8bff, #6c63ff);
  box-shadow: 0 8px 20px rgb(91 139 255 / 32%);
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
  color: #1f2a44;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.2px;
}

.brand-copy small {
  color: #9aa4bd;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.navigation {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
  padding-top: 4px;
}

.navigation-link {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 12px;
  min-height: 46px;
  padding: 0 12px;
  border: 0;
  border-radius: 11px;
  color: #5b6684;
  background: transparent;
  text-align: left;
  text-decoration: none;
  transition:
    background-color 150ms ease,
    color 150ms ease;
}

.navigation-link:hover {
  color: #2f3a58;
  background: #eef2ff;
}

.navigation-link.router-link-active,
.navigation-link--active {
  color: #4c6ef5;
  background: linear-gradient(90deg, #e8edff, #eef2ff);
  font-weight: 600;
}

.navigation-parent-trigger[aria-expanded="true"] {
  color: #2f3a58;
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
  margin: 2px 0 4px 24px;
  padding-left: 14px;
  border-left: 1.5px solid #e4e9f5;
}

.navigation-child-link {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 38px;
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
  color: #2f3a58;
  background: #eef2ff;
}

.navigation-child-link.router-link-active {
  color: #4c6ef5;
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
.app-sidebar--collapsed .navigation-children {
  display: none;
}

.app-sidebar--collapsed .navigation-link {
  justify-content: center;
  padding: 0;
}

@media (max-width: 720px) {
  .brand-copy,
  .navigation-text,
  .navigation-chevron,
  .navigation-children {
    display: none;
  }

  .brand {
    justify-content: center;
    padding-right: 0;
    padding-left: 0;
  }

  .navigation-link {
    justify-content: center;
    padding: 0;
  }
}
</style>
