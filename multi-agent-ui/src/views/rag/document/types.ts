/** RAG 组件间共享的类型定义。 */

/** 知识库表单弹窗提交的载荷。 */
export interface KnowledgeBaseFormPayload {
  name: string;
  description: string;
  visibility: string;
  status: string;
  /** 归属部门（仅新建态且 data_scope=all 可选，null 表示未选） */
  dept_id: string | null;
}

/** 文件夹表单弹窗提交的载荷。 */
export interface FolderFormPayload {
  name: string;
  parent_id: string | null;
  sort_order: number;
  /** 归属知识库，来自页面当前选中的 KB；创建后不可变 */
  knowledge_base_id: string;
}

/** 文档上传弹窗提交的载荷。 */
export interface DocumentUploadFormPayload {
  file: File;
  knowledge_base_id: string;
  folder_id: string | null;
  title: string;
  valid_from?: string;
  valid_until?: string;
  remark: string;
  /** 分块策略：char 通用分块（默认）/ structure 章节分块 / semantic 语义分块 */
  chunk_strategy: string;
}
