import request, { type ApiResult } from "@/utils/request";
import { CATEGORY_URL, type PageResult } from "./index";

/** 分类实体（对应后端 rag_categories.to_dict） */
export interface Category {
  id: string;
  /** 多租户隔离标识，由服务端注入（缺省 'default'），不可变 */
  tenant_id: string;
  parent_id: string | null;
  name: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/** 分类树节点（在扁平 Category 上追加 children，用于 el-tree-select 等树形组件） */
export interface CategoryTreeNode extends Category {
  children: CategoryTreeNode[];
}

/** 将扁平的 parent_id 分类列表组装成树，按 sort_order 升序排列同级节点 */
export function buildCategoryTree(list: Category[]): CategoryTreeNode[] {
  const map = new Map<string, CategoryTreeNode>();
  list.forEach((c) => map.set(c.id, { ...c, children: [] }));
  const roots: CategoryTreeNode[] = [];
  map.forEach((node) => {
    const parent = node.parent_id ? map.get(node.parent_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (nodes: CategoryTreeNode[]) => {
    nodes.sort((a, b) => a.sort_order - b.sort_order);
    nodes.forEach((n) => sortNodes(n.children));
  };
  sortNodes(roots);
  return roots;
}

/** 收集某个分类自身及其全部后代的 id（用于编辑分类时排除自引用与成环） */
export function collectSubtreeIds(list: Category[], rootId: string): Set<string> {
  const childrenMap = new Map<string | null, Category[]>();
  list.forEach((c) => {
    const key = c.parent_id;
    const bucket = childrenMap.get(key);
    if (bucket) bucket.push(c);
    else childrenMap.set(key, [c]);
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

/** 创建分类请求体 */
export interface CategoryCreatePayload {
  name: string;
  parent_id?: string | null;
  sort_order?: number;
}

/** 更新分类请求体（仅提供的字段会被更新，parent_id 可显式置空） */
export interface CategoryUpdatePayload {
  name?: string;
  sort_order?: number;
  parent_id?: string | null;
}

/** 创建分类 */
export function createCategory(payload: CategoryCreatePayload) {
  return request.post<Category, ApiResult<Category>>(CATEGORY_URL.root, payload);
}

/** 分页列出分类参数 */
export interface CategoryListParams {
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 只返回该父分类的直接子分类 */
  parent_id?: string;
  /** 按名称模糊搜索 */
  keyword?: string;
}

/** 分页列出分类：可选按 parent_id/关键词过滤 */
export function listCategories(params: CategoryListParams = {}) {
  return request.get<PageResult<Category>, ApiResult<PageResult<Category>>>(CATEGORY_URL.root, {
    params,
  });
}

/** 按 id 获取分类 */
export function getCategory(categoryId: string) {
  return request.get<Category, ApiResult<Category>>(CATEGORY_URL.byId(categoryId));
}

/** 更新分类的 name/sort_order/parent_id */
export function updateCategory(categoryId: string, payload: CategoryUpdatePayload) {
  return request.put<Category, ApiResult<Category>>(CATEGORY_URL.byId(categoryId), payload);
}

/** 带守卫的物理删除：仅空分类可删除 */
export function deleteCategory(categoryId: string) {
  return request.delete<null, ApiResult<null>>(CATEGORY_URL.byId(categoryId));
}
