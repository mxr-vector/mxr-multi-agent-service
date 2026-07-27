import type { ChatSource } from "@/api/aichat/ai";

export type MessageRole = "user" | "assistant";
export type MessageStatus = "done" | "typing" | "error";

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

export type KnowledgeOption = { label: string; value: number };
export type AiTagOption = { label: string; value: number };
export type KnowledgeLoadStatus = "idle" | "loading" | "loaded" | "error";

export interface AiChatProps {
  title?: string;
  placeholder?: string;
  quickQuestions?: string[];
  databases?: { label: string; value: string }[];
  right?: number;
  bottom?: number;
  kbIds?: number[];
  tagIds?: number[];
  topK?: number;
  similarityThreshold?: number;
}

export type AiChatEmit = {
  (e: "open"): void;
  (e: "close"): void;
  (e: "message-sent", text: string): void;
  (e: "message-received", msg: ChatMessage): void;
};
