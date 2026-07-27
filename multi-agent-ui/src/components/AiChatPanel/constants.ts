export const WELCOME_MESSAGE = "你好！我是 AI 助手，有任何问题都可以问我 ✨";
export const SESSION_TITLE_MAX_LEN = 8;
export const SESSION_TITLE_ELLIPSIS = "…";
export const DATE_LABEL_TODAY = "今天";
export const DATE_LABEL_YESTERDAY = "昨天";

export const SSE_EVENT = {
  THINK: "think",
  ANSWER: "answer",
  MESSAGE: "message",
  SOURCES: "sources",
  RESET: "reset",
  DONE: "done",
} as const;

export const BACKEND_MSG_TYPE = {
  USER: "USER",
  ASSISTANT: "ASSISTANT",
} as const;

export const MSG_STATUS = {
  DONE: "done",
  TYPING: "typing",
  ERROR: "error",
} as const;
