/** RAG 组件间共享的类型定义。 */

/** 知识库表单弹窗提交的载荷。 */
export interface KnowledgeBaseFormPayload {
  name: string;
  description: string;
  category_id: string | null;
  visibility: string;
  status: string;
}

/** 分类表单弹窗提交的载荷。 */
export interface CategoryFormPayload {
  name: string;
  parent_id: string | null;
  sort_order: number;
}
