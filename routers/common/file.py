"""
通用文件路由：文档解析与文本提取。

为全系统提供统一的文档上传解析接口，支持 pdf/docx/markdown/txt/csv/xlsx。
"""

from fastapi import APIRouter, Depends, File, UploadFile

from service.common.file import CommonFileService
from utils.response import R
from utils.user_context import UserContext, get_user_context

router = APIRouter(prefix="/common/file", tags=["OpenAPI - 通用文件"])

_service = CommonFileService()


@router.post("/parse")
async def parse_document(
    file: UploadFile = File(
        ...,
        description="待解析文档（支持 .txt, .md, .docx, .pdf, .xlsx, .csv）",
    ),
    ctx: UserContext = Depends(get_user_context),
):
    """解析上传文档并返回纯文本内容与元数据。"""
    data = await _service.parse_and_extract_text(file)
    return R.success(data=data)
