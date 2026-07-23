/** 前端展示用的轻量格式化工具，供 RAG 各页面共用。 */

/** 将 ISO 时间字符串格式化为 `YYYY-MM-DD HH:mm`，空值返回占位符。 */
export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}
