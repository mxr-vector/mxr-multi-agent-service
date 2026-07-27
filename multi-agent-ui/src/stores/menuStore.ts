/**
 * 动态路由菜单 store：登录后从后端路由菜单接口拉取菜单树的唯一状态源。
 *
 * loadMenus 由路由守卫在首次导航时触发，拉取失败时降级为仅静态导航（loaded 仍置真，
 * 避免守卫无限重试）；登出时由 userStore 调用 reset 清空，下次登录重新拉取。
 */

import { defineStore } from "pinia";
import { ref } from "vue";
import { buildMenuTree, menuApi } from "@/api/system/menu";
import { menusToNavigation, type NavigationItem } from "@/router/navigation";

export const useMenuStore = defineStore("menu", () => {
  /** 后端菜单转换出的动态导航项（树形，供侧边栏与动态路由注册共用） */
  const dynamicItems = ref<NavigationItem[]>([]);
  /** 是否已完成一次菜单加载（含失败降级），守卫据此决定是否触发加载 */
  const loaded = ref(false);

  /** 拉取后端菜单并组装为导航树；失败时保持空菜单但标记已加载 */
  async function loadMenus() {
    try {
      const res = await menuApi.list();
      dynamicItems.value = menusToNavigation(buildMenuTree(res.data ?? []));
    } catch {
      dynamicItems.value = [];
    } finally {
      loaded.value = true;
    }
  }

  /** 清空动态菜单（登出时调用，动态路由的移除由 router 侧负责） */
  function reset() {
    dynamicItems.value = [];
    loaded.value = false;
  }

  return { dynamicItems, loaded, loadMenus, reset };
});
