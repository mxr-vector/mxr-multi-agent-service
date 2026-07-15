from typing import Union
from fastapi import APIRouter, UploadFile, HTTPException, File, Form, Body, Query, Path
from utils.response import R

# 创建路由
router = APIRouter(prefix="/model", tags=["OpenAPI - 模型统一调度接口"])


@router.get("/test")
async def test():
    """
    测试接口
    """
    return R.success(data="测试接口")
