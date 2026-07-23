from typing import Union
from fastapi import APIRouter, UploadFile, HTTPException, File, Form, Body, Query, Path
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/document", tags=["OpenAPI - RAG 文档管理"])
