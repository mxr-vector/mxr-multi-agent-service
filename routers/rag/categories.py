from typing import Union
from fastapi import APIRouter, UploadFile, HTTPException, File, Form, Body, Query, Path
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/categories", tags=["OpenAPI - RAG 分类管理"])
