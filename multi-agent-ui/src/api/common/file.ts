import request, { type ApiResult } from "@/utils/request";

/** 通用文档解析返回结果 */
export interface ParsedDocumentVO {
  filename: string;
  doc_type: string;
  size: number;
  char_count: number;
  content: string;
}

/** 允许上传并解析的文档扩展名集合（统一限定格式） */
export const COMMON_FILE_EXTENSIONS = [
  ".txt",
  ".md",
  ".markdown",
  ".docx",
  ".pdf",
  ".xlsx",
  ".xls",
  ".csv",
] as const;

/** el-upload 接受的 MIME / 扩展名限制字符串 */
export const COMMON_FILE_ACCEPT = COMMON_FILE_EXTENSIONS.join(",");

/**
 * 校验上传文件格式与大小限制
 * @param file 待校验文件对象
 * @param maxSizeMb 最大文件体积（MB，默认 20MB）
 * @returns 错误原因，通过则返回 null
 */
export function validateCommonFile(file: File, maxSizeMb = 20): string | null {
  const name = file.name.toLowerCase();
  const isValidExt = COMMON_FILE_EXTENSIONS.some((ext) => name.endsWith(ext));
  if (!isValidExt) {
    return `不支持的文件格式，仅支持: ${COMMON_FILE_EXTENSIONS.join("、")}`;
  }
  if (file.size > maxSizeMb * 1024 * 1024) {
    return `文件大小不能超过 ${maxSizeMb}MB`;
  }
  return null;
}

export const commonFileApi = {
  /**
   * 上传通用文档并提取纯文本内容
   */
  parse(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    return request.post<ParsedDocumentVO, ApiResult<ParsedDocumentVO>>(
      "/common/file/parse",
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
      }
    );
  },
};
