import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, File, Form, Path, Query, UploadFile
from pydantic import BaseModel

from service.rag.document import DocumentService
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/document", tags=["OpenAPI - RAG 文档管理"])

_service = DocumentService()


class DocumentUpdate(BaseModel):
    """更新文档请求体（仅可编辑元数据；内容/哈希/版本/归属/状态不可变）。"""

    title: Optional[str] = None
    folder_id: Optional[uuid.UUID] = None
    source_uri: Optional[str] = None
    source_system: Optional[str] = None
    doc_type: Optional[str] = None
    metadata: Optional[dict] = None
    source_updated_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    last_verified_at: Optional[str] = None


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(..., description="待上传文件（pdf/markdown/excel/docx）"),
    knowledge_base_id: uuid.UUID = Form(..., description="目标知识库 id"),
    folder_id: Optional[uuid.UUID] = Form(default=None, description="同一知识库内的文件夹 id"),
    source_uri: Optional[str] = Form(
        default=None, description="来源标识，缺省用文件名"
    ),
    source_system: Optional[str] = Form(default=None, description="来源系统"),
    title: Optional[str] = Form(default=None, description="文档标题，缺省用文件名"),
    valid_from: Optional[datetime] = Form(
        default=None, description="有效期起始时间，缺省用服务端 now()"
    ),
    valid_until: Optional[datetime] = Form(
        default=None, description="有效期截止时间，缺省表示长期有效"
    ),
    remark: Optional[str] = Form(
        default=None, description="备注，存入 metadata.remark"
    ),
):
    """上传文件：解析 + 两级切块 + 落库（不向量化）。未变化的重复上传是幂等 no-op。"""
    data = await file.read()
    metadata = {"remark": remark} if remark else None
    doc = await _service.upload(
        knowledge_base_id=knowledge_base_id,
        filename=file.filename,
        data=data,
        source_uri=source_uri,
        source_system=source_system,
        title=title,
        metadata=metadata,
        folder_id=folder_id,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    return R.success(data=doc)


@router.post("/{doc_id}/vectorize")
async def vectorize_document(doc_id: uuid.UUID = Path(...)):
    """单独触发向量化：把当前版本 level 0 叶块写入知识库的 Qdrant 集合。"""
    doc = await _service.vectorize(doc_id)
    return R.success(data=doc)


@router.get("")
async def list_documents(
    knowledge_base_id: uuid.UUID = Query(..., description="按知识库过滤"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    status: Optional[str] = Query(default=None, description="按状态过滤"),
):
    """按知识库分页列出文档（排除软删除的），可选按 status 过滤。"""
    page_result = await _service.list(
        knowledge_base_id, page=page, size=size, status=status
    )
    return R.success(data=page_result)


@router.get("/{doc_id}")
async def get_document(doc_id: uuid.UUID = Path(...)):
    """按 id 获取文档。"""
    doc = await _service.get(doc_id)
    return R.success(data=doc)


@router.put("/{doc_id}")
async def update_document(
    doc_id: uuid.UUID = Path(...),
    payload: DocumentUpdate = Body(...),
):
    """仅元数据更新；不触碰内容/哈希/版本/归属/状态，不再切块或向量化。"""
    changes = payload.model_dump(exclude_unset=True)
    doc = await _service.update(doc_id, changes)
    return R.success(data=doc)
