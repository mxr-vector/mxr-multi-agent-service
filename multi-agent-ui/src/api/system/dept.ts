import request, { type ApiResult } from "@/utils/request";
import { DEPT_URL } from "./index";

/** 部门实体（对应后端 sys_dept.to_dict） */
export interface Dept {
  id: string;
  /** 父部门 id，为空表示顶级部门 */
  parent_id: string | null;
  name: string;
  sort_order: number;
  leader: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/** 部门树节点（在扁平 Dept 上追加 children，用于树形表格/树选择） */
export interface DeptTreeNode extends Dept {
  children: DeptTreeNode[];
}

/** 将扁平的 parent_id 部门列表组装成树，按 sort_order 升序排列同级节点 */
export function buildDeptTree(list: Dept[]): DeptTreeNode[] {
  const map = new Map<string, DeptTreeNode>();
  list.forEach((d) => map.set(d.id, { ...d, children: [] }));
  const roots: DeptTreeNode[] = [];
  map.forEach((node) => {
    const parent = node.parent_id ? map.get(node.parent_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  const sortNodes = (nodes: DeptTreeNode[]) => {
    nodes.sort((a, b) => a.sort_order - b.sort_order);
    nodes.forEach((n) => sortNodes(n.children));
  };
  sortNodes(roots);
  return roots;
}

/** 收集某个部门自身及其全部后代的 id（编辑部门时排除自引用与成环） */
export function collectDeptSubtreeIds(list: Dept[], rootId: string): Set<string> {
  const childrenMap = new Map<string | null, Dept[]>();
  list.forEach((d) => {
    const key = d.parent_id;
    const bucket = childrenMap.get(key);
    if (bucket) bucket.push(d);
    else childrenMap.set(key, [d]);
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

/** 创建部门请求体（parent_id 为空表示顶级部门） */
export interface DeptCreatePayload {
  name: string;
  parent_id?: string | null;
  sort_order?: number;
  leader?: string | null;
  status?: string;
}

/** 更新部门请求体（仅提供的字段会被更新，parent_id 可显式置空升为顶级） */
export interface DeptUpdatePayload {
  name?: string;
  sort_order?: number;
  leader?: string | null;
  status?: string;
  parent_id?: string | null;
}

/** 扁平列出部门参数（不分页，树由前端组装） */
export interface DeptListParams {
  /** 按部门名称模糊搜索 */
  keyword?: string;
  /** 按状态精确过滤 */
  status?: string;
}

/** 部门管理 API：统一通过 deptApi.xx() 调用 */
export const deptApi = {
  /** 创建部门（父部门须存在） */
  create(payload: DeptCreatePayload) {
    return request.post<Dept, ApiResult<Dept>>(DEPT_URL.root, payload);
  },

  /** 扁平列出全部部门（sort_order 升序），树由前端 buildDeptTree 组装 */
  list(params: DeptListParams = {}) {
    return request.get<Dept[], ApiResult<Dept[]>>(DEPT_URL.root, { params });
  },

  /** 按 id 获取部门 */
  get(deptId: string) {
    return request.get<Dept, ApiResult<Dept>>(DEPT_URL.byId(deptId));
  },

  /** 更新部门；变更 parent_id 时后端校验存在性与防环（非自身/后代） */
  update(deptId: string, payload: DeptUpdatePayload) {
    return request.put<Dept, ApiResult<Dept>>(DEPT_URL.byId(deptId), payload);
  },

  /** 带守卫的物理删除：存在子部门或关联用户时拒绝删除 */
  remove(deptId: string) {
    return request.delete<null, ApiResult<null>>(DEPT_URL.byId(deptId));
  },
};
