import type { ChatSource } from "@/api/aichat";

export type MessageRole = "user" | "assistant";

/** 前端消息展示状态；后端 generating/failed 等协议状态在适配层转换。 */
export const MESSAGE_STATUS = {
  DONE: "done",
  TYPING: "typing",
  ERROR: "error",
} as const;

export type MessageStatus = (typeof MESSAGE_STATUS)[keyof typeof MESSAGE_STATUS];

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  time: string;
  status: MessageStatus;
  thinking?: string;
  sources?: ChatSource[];
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
}

export type KnowledgeOption = { label: string; value: string };
export type KnowledgeLoadStatus = "idle" | "loading" | "loaded" | "error";

export interface AiChatProps {
  title?: string;
  placeholder?: string;
  quickQuestions?: string[];
  right?: number;
  bottom?: number;
  /** 固定携带的知识库检索范围（hex id 列表），与面板内选中的知识库合并 */
  kbIds?: string[];
}

export type AiChatEmit = {
  (e: "open"): void;
  (e: "close"): void;
  (e: "message-sent", text: string): void;
  (e: "message-received", msg: ChatMessage): void;
};
