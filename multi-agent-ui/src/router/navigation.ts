import type { RouteMeta } from "vue-router";

export interface NavigationItem extends RouteMeta {
  readonly path: string;
  readonly name: string;
  readonly label: string;
  readonly description: string;
  readonly icon: string;
  readonly group: "工作台" | "管理";
  readonly children?: readonly NavigationItem[];
}

/** icon 键 -> assets/icon/left_icon 下的资源基础名，供侧边栏与顶栏共用 */
export const NAV_ICON_ASSET: Record<string, string> = {
  dashboard: "zhihuizhongxin",
  chat: "zhishihudong",
  workflow: "lunhuantuguanli",
  rag: "shujufenxi",
  knowledge: "danganhe",
  document: "wenjian",
  agent: "keji",
  settings: "xitongguanli",
};

export const navigationItems: readonly NavigationItem[] = [
  {
    path: "/overview",
    name: "overview",
    label: "工作台",
    description: "掌握团队与任务的实时进展。",
    icon: "dashboard",
    group: "工作台",
  },
  {
    path: "/conversations",
    name: "conversations",
    label: "会话中心",
    description: "回顾近期对话和智能体产出。",
    icon: "chat",
    group: "工作台",
  },
  {
    path: "/workflows",
    name: "workflows",
    label: "工作流",
    description: "将协作步骤编排为可复用的自动化流程。",
    icon: "workflow",
    group: "工作台",
  },
  {
    path: "/rag",
    name: "rag",
    label: "RAG 系统",
    description: "管理检索增强生成所需的知识与文档。",
    icon: "rag",
    group: "管理",
    children: [
      {
        path: "/rag/knowledge-base",
        name: "rag-knowledge-base",
        label: "AI 知识库管理",
        description: "集中管理可供检索的知识库。",
        icon: "knowledge",
        group: "管理",
      },
      {
        path: "/rag/ducument",
        name: "rag-ducument",
        label: "文档管理",
        description: "上传、处理并维护知识库文档。",
        icon: "document",
        group: "管理",
      },
    ],
  },
  {
    path: "/agents",
    name: "agents",
    label: "智能体",
    description: "创建、配置并监控你的智能体。",
    icon: "agent",
    group: "工作台",
  },
  {
    path: "/settings",
    name: "settings",
    label: "系统管理",
    description: "调整工作区、成员与连接配置。",
    icon: "settings",
    group: "管理",
  },
];
