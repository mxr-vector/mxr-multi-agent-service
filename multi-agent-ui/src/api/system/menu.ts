import request, { type ApiResult } from "@/utils/request";
import { MENU_URL } from "./index";

/** 菜单实体（对应后端 sys_menu.to_dict） */
export interface Menu {
  id: string;
  /** 父菜单 id，为空表示顶级节点 */
  parent_id: string | null;
  /** 菜单类型：dir 目录 / menu 菜单 / button 按钮，创建后不可变 */
  menu_type: string;
  /** 路由名称（menu 类型使用） */
  name: string | null;
  /** 路由路径（dir/menu 类型使用） */
  path: string | null;
  /** 前端组件标识（menu 类型使用） */
  component: string | null;
  /** 显示名称 */
  label: string;
  icon: string | null;
  /** 权限标识（如 'system:user:add'，button 类型使用） */
  perms: string | null;
  visible: boolean;
  sort_order: number;
  status: string;
  created_at: string;
  updated_at: string;
}

/** 菜单树节点（在扁平 Menu 上追加 children，用于树形表格/分配菜单树） */
export interface MenuTreeNode extends Menu {
  children: MenuTreeNode[];
}

/** 将扁平的 parent_id 菜单列表组装成树，按 sort_order 升序排列同级节点 */
export function buildMenuTree(list: Menu[]): MenuTreeNode[] {
  const map = new Map<string, MenuTreeNode>();
  list.forEach((m) => map.set(m.id, { ...m, children: [] }));
  const roots: MenuTreeNode[] = [];
  map.forEach((node) => {
    const parent = node.parent_id ? map.get(node.parent_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (nodes: MenuTreeNode[]) => {
    nodes.sort((a, b) => a.sort_order - b.sort_order);
    nodes.forEach((n) => sortNodes(n.children));
  };
  sortNodes(roots);
  return roots;
}

/** 收集某个菜单自身及其全部后代的 id（编辑菜单时排除自引用与成环） */
export function collectMenuSubtreeIds(list: Menu[], rootId: string): Set<string> {
  const childrenMap = new Map<string | null, Menu[]>();
  list.forEach((m) => {
    const key = m.parent_id;
    const bucket = childrenMap.get(key);
    if (bucket) bucket.push(m);
    else childrenMap.set(key, [m]);
  });
  const ids = new Set<string>([rootId]);
  const stack = [rootId];
  while (stack.length) {
    const cur = stack.pop() as string;
    (childrenMap.get(cur) ?? []).forEach((child) => {
      if (!ids.has(child.id)) {
        ids.add(child.id);
        stack.push(child.id);
      }
    });
  }
  return ids;
}

/** 创建菜单请求体（menu_type 取 dir/menu/button，创建后不可变） */
export interface MenuCreatePayload {
  menu_type: string;
  label: string;
  parent_id?: string | null;
  name?: string | null;
  path?: string | null;
  component?: string | null;
  icon?: string | null;
  perms?: string | null;
  visible?: boolean;
  sort_order?: number;
  status?: string;
}

/** 更新菜单请求体（仅提供的字段会被更新，parent_id 可显式置空升为顶级；menu_type 不可变） */
export interface MenuUpdatePayload {
  label?: string;
  name?: string | null;
  path?: string | null;
  component?: string | null;
  icon?: string | null;
  perms?: string | null;
  visible?: boolean;
  sort_order?: number;
  status?: string;
  parent_id?: string | null;
}

/** 扁平列出菜单参数（不分页，树由前端组装） */
export interface MenuListParams {
  /** 按菜单名称模糊搜索 */
  keyword?: string;
  /** 按状态精确过滤 */
  status?: string;
}

/** 菜单管理 API：统一通过 menuApi.xx() 调用 */
export const menuApi = {
  /** 创建菜单（menu_type 枚举校验、父节点须存在） */
  create(payload: MenuCreatePayload) {
    return request.post<Menu, ApiResult<Menu>>(MENU_URL.root, payload);
  },

  /** 扁平列出全部菜单（sort_order 升序），树由前端 buildMenuTree 组装 */
  list(params: MenuListParams = {}) {
    return request.get<Menu[], ApiResult<Menu[]>>(MENU_URL.root, { params });
  },

  /** 按 id 获取菜单 */
  get(menuId: string) {
    return request.get<Menu, ApiResult<Menu>>(MENU_URL.byId(menuId));
  },

  /** 更新菜单（menu_type 不可变；变更 parent_id 时后端校验存在性与防环） */
  update(menuId: string, payload: MenuUpdatePayload) {
    return request.put<Menu, ApiResult<Menu>>(MENU_URL.byId(menuId), payload);
  },

  /** 带守卫的物理删除：存在子菜单或仍被角色绑定时拒绝删除 */
  remove(menuId: string) {
    return request.delete<null, ApiResult<null>>(MENU_URL.byId(menuId));
  },
};
