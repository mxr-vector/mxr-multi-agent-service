import type { RouteMeta } from "vue-router";
import type { MenuTreeNode } from "@/api/system/menu";

export interface NavigationItem extends RouteMeta {
  readonly path: string;
  readonly name: string;
  readonly label: string;
  readonly icon: string;
  /** 页面副标题描述（静态菜单专用，后端菜单暂无该字段） */
  readonly description?: string;
  /** 前端组件键（来自后端菜单 component 字段，由 router 的 viewModules 映射为真实组件） */
  readonly component?: string | null;
  /** 后端菜单节点类型（dir/menu），静态导航无该字段；dir 仅作分组不注册路由 */
  readonly type?: string;
  readonly children?: readonly NavigationItem[];
}

/** icon 键 -> assets/icon/left_icon 下的资源基础名，供侧边栏与顶栏共用 */
export const NAV_ICON_ASSET: Record<string, string> = {
  dashboard: "zhihuizhongxin",
  workflow: "lunhuantuguanli",
  rag: "shujufenxi",
  knowledge: "danganhe",
  document: "wenjian",
  agent: "keji",
  settings: "xitongguanli",
  user: "yonghuguanli",
  role: "jiaoseguanli",
  dept: "bumenguanli",
  menu: "mobanguanli",
  dict: "shujuzidianguanli",
  config: "bianmaguize",
};

/** 静态导航：仅保留工作台，其余菜单均来自后端路由菜单接口 */
export const navigationItems: readonly NavigationItem[] = [
  {
    path: "/overview",
    name: "overview",
    label: "工作台",
    description: "掌握团队与任务的实时进展。",
    icon: "dashboard",
  },
];

/**
 * 将后端菜单树转换为导航项：
 * 过滤 button 类型与隐藏/停用节点，dir 节点保留 children（空目录也保留，仅作分组），
 * menu 节点携带 component 组件键。
 */
export function menusToNavigation(nodes: MenuTreeNode[]): NavigationItem[] {
  return nodes
    .filter((node) => node.menu_type !== "button" && node.visible && node.status === "active")
    .map((node) => {
      const children = menusToNavigation(node.children);
      return {
        path: node.path ?? "",
        name: node.name ?? node.id,
        label: node.label,
        icon: node.icon ?? "document",
        component: node.component,
        type: node.menu_type,
        ...(children.length ? { children } : {}),
      };
    })
    .filter((item) => item.type === "dir" || item.path || item.children?.length);
}
