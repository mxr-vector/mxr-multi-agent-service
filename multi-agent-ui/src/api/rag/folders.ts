import request, { type ApiResult } from "@/utils/request";
import { FOLDER_URL, type PageResult } from "./index";

/** 文件夹实体（对应后端 rag_folders.to_dict） */
export interface Folder {
  id: string;
  /** 归属组织/部门（逻辑指向 sys_dept.id，空字符串表示未归属），由服务端注入，不可变 */
  dept_id: string;
  /** 所属知识库 id，创建后不可变 */
  knowledge_base_id: string;
  parent_id: string | null;
  name: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/** 文件夹树节点（在扁平 Folder 上追加 children，用于 el-tree-select 等树形组件） */
export interface FolderTreeNode extends Folder {
  children: FolderTreeNode[];
}

/** 将扁平的 parent_id 文件夹列表组装成树，按 sort_order 升序排列同级节点 */
export function buildFolderTree(list: Folder[]): FolderTreeNode[] {
  const map = new Map<string, FolderTreeNode>();
  list.forEach((f) => map.set(f.id, { ...f, children: [] }));
  const roots: FolderTreeNode[] = [];
  map.forEach((node) => {
    const parent = node.parent_id ? map.get(node.parent_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (nodes: FolderTreeNode[]) => {
    nodes.sort((a, b) => a.sort_order - b.sort_order);
    nodes.forEach((n) => sortNodes(n.children));
  };
  sortNodes(roots);
  return roots;
}

/** 收集某个文件夹自身及其全部后代的 id（用于编辑文件夹时排除自引用与成环） */
export function collectSubtreeIds(list: Folder[], rootId: string): Set<string> {
  const childrenMap = new Map<string | null, Folder[]>();
  list.forEach((f) => {
    const key = f.parent_id;
    const bucket = childrenMap.get(key);
    if (bucket) bucket.push(f);
    else childrenMap.set(key, [f]);
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

/** 创建文件夹请求体（knowledge_base_id 必填，创建后不可变） */
export interface FolderCreatePayload {
  name: string;
  knowledge_base_id: string;
  parent_id?: string | null;
  sort_order?: number;
}

/** 更新文件夹请求体（仅提供的字段会被更新，parent_id 可显式置空；knowledge_base_id 不可变） */
export interface FolderUpdatePayload {
  name?: string;
  sort_order?: number;
  parent_id?: string | null;
}

/** 分页列出文件夹参数 */
export interface FolderListParams {
  /** 所属知识库 id，必填 */
  knowledge_base_id: string;
  /** 页码，从 1 开始（默认 1） */
  page?: number;
  /** 每页数量（1-200，默认 20） */
  size?: number;
  /** 只返回该父文件夹的直接子文件夹 */
  parent_id?: string;
  /** 按名称模糊搜索 */
  keyword?: string;
}

/** 文件夹管理 API：统一通过 folderApi.xx() 调用 */
export const folderApi = {
  /** 创建文件夹（归属指定知识库） */
  create(payload: FolderCreatePayload) {
    return request.post<Folder, ApiResult<Folder>>(FOLDER_URL.root, payload);
  },

  /** 分页列出某知识库内的文件夹：可选按 parent_id/关键词过滤 */
  list(params: FolderListParams) {
    return request.get<PageResult<Folder>, ApiResult<PageResult<Folder>>>(FOLDER_URL.root, {
      params,
    });
  },

  /** 按 id 获取文件夹 */
  get(folderId: string) {
    return request.get<Folder, ApiResult<Folder>>(FOLDER_URL.byId(folderId));
  },

  /** 更新文件夹的 name/sort_order/parent_id（knowledge_base_id 不可变） */
  update(folderId: string, payload: FolderUpdatePayload) {
    return request.put<Folder, ApiResult<Folder>>(FOLDER_URL.byId(folderId), payload);
  },

  /** 带守卫的物理删除：仅空文件夹（无子文件夹、无文档）可删除 */
  remove(folderId: string) {
    return request.delete<null, ApiResult<null>>(FOLDER_URL.byId(folderId));
  },
};
