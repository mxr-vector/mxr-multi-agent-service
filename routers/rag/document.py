import asyncio
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, Path, Query, UploadFile
from pydantic import BaseModel

from exception.bad_except import bad_except
from service.rag.document import DocumentService
from utils.env import ENV
from utils.response import R
from utils.user_context import UserContext, get_user_context

# 创建路由
router = APIRouter(prefix="/rag/document", tags=["OpenAPI - RAG 文档管理"])

_service = DocumentService()

# 后台向量化作业的强引用集合，防止 create_task 产物被 GC 提前回收
_vectorize_tasks: set[asyncio.Task] = set()


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
    file: UploadFile = File(
        ..., description="待上传文件（pdf/markdown/excel/docx/text/csv）"
    ),
    knowledge_base_id: uuid.UUID = Form(..., description="目标知识库 id"),
    folder_id: Optional[uuid.UUID] = Form(
        default=None, description="同一知识库内的文件夹 id"
    ),
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
    dept_id: Optional[str] = Form(
        default=None,
        description="归属部门（32 位 hex；仅 data_scope=all 生效，须为已存在部门）",
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """上传文件：解析 + 两级切块 + 落库（不向量化）。未变化的重复上传是幂等 no-op。"""
    data = await file.read()
    # 以实际读到的字节数校验（Content-Length 可伪造），超限在解析前即拒绝
    max_bytes = ENV.upload_max_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        bad_except(f"文件超过大小上限（{ENV.upload_max_size_mb}MB）: {file.filename}")
    metadata = {"remark": remark} if remark else None
    doc = await _service.upload(
        ctx,
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
        dept_id=dept_id,
    )
    return R.success(data=doc)


# 注意：/status 必须声明在 GET /{doc_id} 之前，否则 "status" 会被当作 UUID 路径参数解析
@router.get("/status")
async def batch_document_status(
    ids: str = Query(..., description="逗号分隔的文档 id 列表，上限 200"),
):
    """批量查询文档向量化状态，返回 [{id, status}, ...]，供前端轮询。"""
    raw = [part.strip() for part in ids.split(",") if part.strip()]
    if len(raw) > 200:
        raw = raw[:200]
    try:
        parsed = [uuid.UUID(part) for part in raw]
    except ValueError:
        return R.fail(msg="ids 包含非法的 UUID")
    items = await _service.statuses(parsed)
    return R.success(data=items)


@router.post("/{doc_id}/vectorize")
async def vectorize_document(doc_id: uuid.UUID = Path(...)):
    """异步触发向量化：置 reindexing 后立即返回，embed/写 Qdrant 在后台任务中完成。"""
    doc = await _service.vectorize(doc_id)
    # 仅在触发校验通过后才排入后台作业，被拒绝的触发不会入队；
    # 用 create_task 而非 BackgroundTasks：作业与响应生命周期完全解耦，
    # 确保响应先刷给客户端，不受中间件链路的响应体中继影响
    task = asyncio.create_task(_service.vectorize_job(doc_id))
    _vectorize_tasks.add(task)
    task.add_done_callback(_vectorize_tasks.discard)
    return R.success(data=doc)


@router.get("")
async def list_documents(
    knowledge_base_id: uuid.UUID = Query(..., description="按知识库过滤"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    status: Optional[str] = Query(default=None, description="按状态过滤"),
    dept_ids: Optional[list[str]] = Query(
        default=None,
        description="按部门过滤（可重复传参，32 位 hex；仅 data_scope=all 生效）",
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """按知识库分页列出文档（排除软删除的），可选按 status 过滤；部门边界按 data_scope 强制。"""
    page_result = await _service.list(
        ctx, knowledge_base_id, page=page, size=size, status=status, dept_ids=dept_ids
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
