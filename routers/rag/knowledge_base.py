from typing import Union
from fastapi import APIRouter, UploadFile, HTTPException, File, Form, Body, Query, Path
from utils.response import R

# 创建路由
router = APIRouter(prefix="/rag/knowledge-base", tags=["OpenAPI - RAG 知识库管理"])
