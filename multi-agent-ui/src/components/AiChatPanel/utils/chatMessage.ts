import type { ChatSource } from "@/api/aichat/ai";
import { DATE_LABEL_TODAY, DATE_LABEL_YESTERDAY, MSG_STATUS, WELCOME_MESSAGE } from "../constants";
import type { ChatMessage } from "../types";

const SOURCE_REF_PATTERN = /(?:\[([0-9０-９]+)\]|【([0-9０-９]+)】)/g;
const FENCED_CODE_BLOCK_PATTERN = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
const SENTENCE_BOUNDARY_PATTERN = /[。！？!?；;\n]/;
const THINK_TAG_PATTERN = /<\/?think>/gi;

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
  status: MSG_STATUS.DONE,
  time: timeNow(),
  content: WELCOME_MESSAGE,
});

export function normalizeSources(data: unknown): ChatSource[] {
  if (!data || typeof data !== "object") return [];
  const sources = (data as { sources?: unknown }).sources;
  if (!Array.isArray(sources)) return [];
  return sources
    .map((source): ChatSource | null => {
      if (!source || typeof source !== "object") return null;
      const item = source as Record<string, unknown>;
      const index = Number(item.index);
      if (!Number.isFinite(index)) return null;
      return {
        index,
        documentId: Number(item.documentId) || 0,
        documentName: String(item.documentName ?? ""),
        kbId: Number(item.kbId) || 0,
        kbName: String(item.kbName ?? ""),
        similarityScore: Number(item.similarityScore) || 0,
        content: String(item.content ?? item.contentSnippet ?? ""),
        contentSnippet: typeof item.contentSnippet === "string" ? item.contentSnippet : undefined,
      };
    })
    .filter((source): source is ChatSource => Boolean(source));
}

export function getMessageSourceMarkdown(msg: ChatMessage): string {
  if (!msg.content) return "";
  return formatSourceRefsOutsideCodeBlocks(msg.content);
}

export function splitThinkContent(content: string): { content: string; thinking?: string } {
  if (!THINK_TAG_PATTERN.test(content)) return { content };
  THINK_TAG_PATTERN.lastIndex = 0;

  let visibleContent = "";
  const thinkingParts: string[] = [];
  let cursor = 0;
  let thinkingStart: number | null = null;

  for (const match of content.matchAll(THINK_TAG_PATTERN)) {
    const tag = match[0].toLowerCase();
    const index = match.index ?? 0;

    if (tag === "<think>") {
      if (thinkingStart === null) {
        visibleContent += content.slice(cursor, index);
        thinkingStart = index + match[0].length;
      }
      cursor = index + match[0].length;
      continue;
    }

    if (thinkingStart !== null) {
      const thinking = content.slice(thinkingStart, index).trim();
      if (thinking) thinkingParts.push(thinking);
      thinkingStart = null;
    } else {
      visibleContent += content.slice(cursor, index);
    }
    cursor = index + match[0].length;
  }

  if (thinkingStart !== null) {
    const thinking = content.slice(thinkingStart).trim();
    if (thinking) thinkingParts.push(thinking);
  } else {
    visibleContent += content.slice(cursor);
  }

  const thinking = thinkingParts.join("\n\n");
  return {
    content: visibleContent.trim(),
    ...(thinking ? { thinking } : {}),
  };
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
