import type { ChatSource } from "@/api/aichat";
import { DATE_LABEL_TODAY, DATE_LABEL_YESTERDAY, WELCOME_MESSAGE } from "../constants";
import { MESSAGE_STATUS, type ChatMessage } from "../types";

const SOURCE_REF_PATTERN = /(?:\[([0-9０-９]+)\]|【([0-9０-９]+)】)/g;
const FENCED_CODE_BLOCK_PATTERN = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
const SENTENCE_BOUNDARY_PATTERN = /[。！？!?；;\n]/;

export const uid = (): string => Math.random().toString(36).slice(2, 9);

export const timeNow = (): string =>
  new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

export const formatDate = (ts: number): string => {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const then = new Date(ts);
  then.setHours(0, 0, 0, 0);
  const diff = now.getTime() - then.getTime();
  if (diff === 0) return DATE_LABEL_TODAY;
  if (diff === 86_400_000) return DATE_LABEL_YESTERDAY;
  return new Date(ts).toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
};

export const makeWelcome = (): ChatMessage => ({
  id: uid(),
  role: "assistant",
  status: MESSAGE_STATUS.DONE,
  time: timeNow(),
  content: WELCOME_MESSAGE,
});

/** 归一化后端 sources 列表（SSE sources 帧 / 消息历史的 sources 字段） */
export function normalizeSources(data: unknown): ChatSource[] {
  if (!Array.isArray(data)) return [];
  return data
    .map((source): ChatSource | null => {
      if (!source || typeof source !== "object") return null;
      const item = source as Record<string, unknown>;
      const index = Number(item.index);
      if (!Number.isFinite(index)) return null;
      return {
        index,
        text: String(item.text ?? ""),
        source: String(item.source ?? ""),
        score: typeof item.score === "number" ? item.score : null,
        knowledge_base_id:
          typeof item.knowledge_base_id === "string" ? item.knowledge_base_id : null,
        chapter_title: typeof item.chapter_title === "string" ? item.chapter_title : null,
        document_id: typeof item.document_id === "string" ? item.document_id : null,
        chunk_id: item.chunk_id != null ? String(item.chunk_id) : null,
        page_start: typeof item.page_start === "number" ? item.page_start : null,
        page_end: typeof item.page_end === "number" ? item.page_end : null,
        document_name: typeof item.document_name === "string" ? item.document_name : null,
        kb_name: typeof item.kb_name === "string" ? item.kb_name : null,
        similarity_percent:
          typeof item.similarity_percent === "number" ? item.similarity_percent : null,
        similarity_level: typeof item.similarity_level === "string" ? item.similarity_level : null,
      };
    })
    .filter((source): source is ChatSource => Boolean(source));
}

export function getMessageSourceMarkdown(msg: ChatMessage): string {
  if (!msg.content) return "";
  return formatSourceRefsOutsideCodeBlocks(msg.content);
}

function formatSourceRefsOutsideCodeBlocks(content: string): string {
  return content
    .split(FENCED_CODE_BLOCK_PATTERN)
    .map((part) => (isFencedCodeBlock(part) ? part : formatCitedSentences(part)))
    .join("");
}

function isFencedCodeBlock(value: string): boolean {
  return value.startsWith("```") || value.startsWith("~~~");
}

function formatCitedSentences(content: string): string {
  let result = "";
  let sentence = "";

  for (const char of content) {
    sentence += char;
    if (SENTENCE_BOUNDARY_PATTERN.test(char)) {
      result += formatSentenceSourceRefs(sentence);
      sentence = "";
    }
  }

  return result + formatSentenceSourceRefs(sentence);
}

function formatSentenceSourceRefs(sentence: string): string {
  return sentence.replace(SOURCE_REF_PATTERN, (_match, bracketIndexText, chineseIndexText) => {
    const indexText = bracketIndexText || chineseIndexText;
    const sourceIndex = normalizeSourceRefIndex(indexText);
    return `<sup class="afc-source-ref" data-source-index="${sourceIndex}">[${sourceIndex}]</sup>`;
  });
}

function normalizeSourceRefIndex(value: string): string {
  return value.replace(/[０-９]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0xfee0));
}
