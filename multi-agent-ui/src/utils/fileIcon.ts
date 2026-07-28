/**
 * 文件类型 -> assets/icon/document 下的彩色图标名映射。
 * 命中扩展名/文档类型返回彩色图标，否则回退到通用单色文件图标。
 */

const EXT_TO_ICON: Record<string, string> = {
  pdf: "PDF",
  md: "MD",
  markdown: "MD",
  xlsx: "XLSX",
  xls: "XLSX",
  excel: "XLSX",
  docx: "DOCX",
  doc: "DOCX",
  word: "DOCX",
  pptx: "PPTX",
  ppt: "PPTX",
  json: "JSON",
  html: "HTML",
  htm: "HTML",
  xml: "XML",
  yaml: "YAML",
  yml: "YAML",
  sql: "SQL",
  js: "JS",
  css: "CSS",
  png: "PNG",
  jpg: "JPG",
  jpeg: "JPG",
  webp: "WEBP",
  mp3: "MP3",
  wav: "WAV",
  flac: "FLAC",
  mp4: "MP4",
  // txt/text 与 csv 暂无专属彩色图标资源，刻意不映射，回退到通用文件图标（wenjian）
};

export interface FileIconMeta {
  /** SvgIcon 的 name（资源基础名） */
  name: string;
  /** 是否保留原始多色填充 */
  colored: boolean;
}

/** 从路径/文件名中提取扩展名（不含点），无扩展名返回 null */
function extOf(uri?: string | null): string | null {
  if (!uri) return null;
  const clean = uri.split(/[?#]/)[0];
  const dot = clean.lastIndexOf(".");
  if (dot < 0 || dot === clean.length - 1) return null;
  return clean.slice(dot + 1);
}

/** 依据 doc_type、source_uri、title 推断文件类型图标 */
export function resolveFileIcon(input: {
  doc_type?: string | null;
  source_uri?: string | null;
  title?: string | null;
}): FileIconMeta {
  const candidates = [input.doc_type, extOf(input.source_uri), extOf(input.title)];
  for (const candidate of candidates) {
    if (!candidate) continue;
    const icon = EXT_TO_ICON[candidate.toLowerCase()];
    if (icon) return { name: icon, colored: true };
  }
  return { name: "wenjian", colored: false };
}
