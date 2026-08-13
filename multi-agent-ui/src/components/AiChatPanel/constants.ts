export const WELCOME_MESSAGE = "你好！我是 AI 助手，有任何问题都可以问我 ✨";
export const SESSION_TITLE_MAX_LEN = 8;
export const SESSION_TITLE_ELLIPSIS = "…";
export const DATE_LABEL_TODAY = "今天";
export const DATE_LABEL_YESTERDAY = "昨天";

/** 词典类型键：思考强度等级（字典管理页维护，前端不做硬编码回退） */
export const REASONING_EFFORT_DICT_TYPE = "reasoning_effort";

/**
 * 词典类型键：SSE 事件名（字典管理页维护，value 即事件名；
 * 事件名映射解析见 api/aichat/ai.ts 的 resolveSseEventMap，缺失时回落协议默认名）
 */
export const SSE_EVENT_DICT_TYPE = "sse_event";
