"""
通用文件服务：文档解析与纯文本抽取。

从 RAG 专属摄取逻辑中抽离出无向量化、无库表依赖的轻量通用能力，
供全局 AI 问答附件上传、剧本创作参考文档等业务场景复用。
"""

from fastapi import UploadFile

from exception.bad_except import bad_except
from utils.file_ingest import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    detect_doc_type,
    extract_text_from_file,
    read_upload_capped,
)
from utils.logger import logger

# 默认单文件解析大小上限 20MB
_DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024


class CommonFileService:
    """通用文件解析服务。"""

    async def parse_and_extract_text(
        self, file: UploadFile, max_bytes: int = _DEFAULT_MAX_FILE_BYTES
    ) -> dict:
        """读取上传文件并提取全文纯文本及元数据。"""
        filename = file.filename or ""
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
            ext_list = ", ".join(SUPPORTED_DOCUMENT_EXTENSIONS)
            bad_except(f"不支持的文件格式: {ext or '无扩展名'}，仅支持: {ext_list}")

        data = await read_upload_capped(file, max_bytes)
        doc_type = detect_doc_type(filename)
        content = extract_text_from_file(filename, data)
        logger.info(
            f"[CommonFile] 成功解析文档: {filename} (类型={doc_type}, 大小={len(data)}B, 字符数={len(content)})"
        )
        return {
            "filename": filename,
            "doc_type": doc_type,
            "size": len(data),
            "char_count": len(content),
            "content": content,
        }
