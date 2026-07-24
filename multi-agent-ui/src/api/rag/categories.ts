import request, { type ApiResult } from "@/utils/request";
import { CATEGORY_URL } from "./index";

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

/** 扁平列出分类：省略 parentId 返回全部，传入则只返回其直接子分类 */
export function listCategories(parentId?: string) {
  return request.get<Category[], ApiResult<Category[]>>(CATEGORY_URL.root, {
    params: { parent_id: parentId },
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
