"""
文件摄取工具（解析 + 分块，纯预处理，不落库、不做向量化）。

职责边界（对应设计 D3）：
- 按文件类型（pdf/markdown/excel/docx）把上传内容解析为完整 UTF-8 文本；
- 计算 content_hash = sha256(全文)，供增量同步判断源文件是否变更；
- 产出两级父子块树：level 1 父块 + level 0 叶块，叶块携带 parent 引用、
  每级顺序号 chunk_index、以及相对父块的 char_start/char_end 偏移；
- PDF 按页解析以便回填 page_start/page_end。

该模块只依赖纯 Python 解析器与字符级切分器，符合"HTTP-only 模型推理"原则，
不引入任何模型调用。业务层（service/rag/document.py）负责把产出持久化。
"""

import hashlib
import io
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from exception.bad_except import bad_except

# 两级切分窗口：level 1 父块给回写上下文，level 0 叶块作检索单元
PARENT_CHUNK_SIZE = 2000
CHILD_CHUNK_SIZE = 400
CHILD_CHUNK_OVERLAP = 80

# 支持的文件后缀 -> doc_type
_EXTENSION_DOC_TYPE = {
    "pdf": "pdf",
    "md": "markdown",
    "markdown": "markdown",
    "xlsx": "excel",
    "xls": "excel",
    "docx": "docx",
}


def detect_doc_type(filename: str) -> str:
    """
    从文件名后缀推断 doc_type，不支持的类型抛业务异常（转为友好失败）。
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    doc_type = _EXTENSION_DOC_TYPE.get(ext)
    if doc_type is None:
        bad_except(f"不支持的文件类型: {filename or '(无扩展名)'}")
    return doc_type


# ---------- 各类型解析：返回 (full_text, page_ranges) ----------
# page_ranges 为 [(page_number, start_char, end_char), ...]，非分页格式为空列表


def _parse_pdf(data: bytes) -> tuple[str, list[tuple[int, int, int]]]:
    """按页解析 PDF 文本，记录每页在全文中的字符区间以便回填页码。"""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    page_ranges: list[tuple[int, int, int]] = []
    cursor = 0
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        start = cursor
        parts.append(page_text)
        cursor += len(page_text)
        page_ranges.append((page_number, start, cursor))
        # 页间以换行分隔（不计入某一页区间）
        parts.append("\n")
        cursor += 1
    full_text = "".join(parts)
    return full_text, page_ranges


def _parse_docx(data: bytes) -> tuple[str, list[tuple[int, int, int]]]:
    """解析 docx，按段落拼接为纯文本；Word 无稳定页码，page_ranges 留空。"""
    from docx import Document as DocxDocument

    doc = DocxDocument(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    return text, []


def _parse_xlsx(data: bytes) -> tuple[str, list[tuple[int, int, int]]]:
    """解析 xlsx，逐表逐行把单元格以制表符/换行拼接为纯文本。"""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        lines.append(f"# {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            lines.append("\t".join(cells))
    wb.close()
    return "\n".join(lines), []


def _parse_markdown(data: bytes) -> tuple[str, list[tuple[int, int, int]]]:
    """Markdown 直接按 UTF-8 文本处理（宽松解码）。"""
    return data.decode("utf-8", errors="replace"), []


_PARSERS = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "excel": _parse_xlsx,
    "markdown": _parse_markdown,
}


def _page_for_offset(
    page_ranges: list[tuple[int, int, int]], offset: int
) -> int | None:
    """把全文字符偏移映射到页码；无分页信息或越界时返回 None。"""
    if not page_ranges:
        return None
    for page_number, start, end in page_ranges:
        if start <= offset < end:
            return page_number
    # 落在末尾换行等边界时归到最后一页
    return page_ranges[-1][0]


def _find_offset(haystack: str, needle: str, cursor: int) -> int:
    """从 cursor 起定位子串偏移，找不到则退化为全局查找。"""
    idx = haystack.find(needle, cursor)
    if idx == -1:
        idx = haystack.find(needle)
    return max(idx, 0)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_file(filename: str, data: bytes) -> dict[str, Any]:
    """
    把上传文件解析为文档字段 + 两级父子块树（不落库、不向量化）。

    返回结构：
    {
      "doc_type": str,
      "content": str,               # 解析出的完整文本
      "content_hash": str,          # sha256(content)
      "parents": [                  # level 1 父块
        {
          "chunk_index": int,       # 父块在 level 1 内的顺序号
          "content": str,
          "char_start": int,        # 相对全文
          "char_end": int,
          "page_start": int | None,
          "page_end": int | None,
          "chapter_title": None,
          "content_hash": str,
          "children": [             # level 0 叶块
            {
              "chunk_index": int,   # 叶块在 level 0 内的全局顺序号
              "content": str,
              "char_start": int,    # 相对父块
              "char_end": int,
              "page_start": int | None,
              "page_end": int | None,
              "chapter_title": None,
              "content_hash": str,
            }, ...
          ],
        }, ...
      ],
    }
    """
    doc_type = detect_doc_type(filename)
    parser = _PARSERS[doc_type]
    full_text, page_ranges = parser(data)
    content_hash = _sha256(full_text)

    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=PARENT_CHUNK_SIZE, chunk_overlap=0
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE, chunk_overlap=CHILD_CHUNK_OVERLAP
    )

    parent_texts = parent_splitter.split_text(full_text)
    # 空文档或纯空白时也产出一个覆盖全文的父块，保证结构完整
    if not parent_texts:
        parent_texts = [full_text]

    parents: list[dict[str, Any]] = []
    doc_cursor = 0
    leaf_index = 0  # level 0 全局顺序号（跨父块连续）
    for parent_index, parent_text in enumerate(parent_texts):
        p_start = _find_offset(full_text, parent_text, doc_cursor)
        p_end = p_start + len(parent_text)
        doc_cursor = p_start + 1

        child_texts = child_splitter.split_text(parent_text)
        if not child_texts:
            child_texts = [parent_text]

        children: list[dict[str, Any]] = []
        child_cursor = 0
        for child_text in child_texts:
            c_start = _find_offset(parent_text, child_text, child_cursor)
            c_end = c_start + len(child_text)
            child_cursor = c_start + 1

            abs_start = p_start + c_start
            abs_end = p_start + c_end
            children.append(
                {
                    "chunk_index": leaf_index,
                    "content": child_text,
                    "char_start": c_start,
                    "char_end": c_end,
                    "page_start": _page_for_offset(page_ranges, abs_start),
                    "page_end": _page_for_offset(
                        page_ranges, max(abs_end - 1, abs_start)
                    ),
                    "chapter_title": None,
                    "content_hash": _sha256(child_text),
                }
            )
            leaf_index += 1

        parents.append(
            {
                "chunk_index": parent_index,
                "content": parent_text,
                "char_start": p_start,
                "char_end": p_end,
                "page_start": _page_for_offset(page_ranges, p_start),
                "page_end": _page_for_offset(page_ranges, max(p_end - 1, p_start)),
                "chapter_title": None,
                "content_hash": _sha256(parent_text),
                "children": children,
            }
        )

    return {
        "doc_type": doc_type,
        "content": full_text,
        "content_hash": content_hash,
        "parents": parents,
    }
