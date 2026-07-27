"""
认证路由（登录 / 登出 / 当前用户）。

登录接口挂 /public/auth/login，天然命中中间件 /public* 白名单免鉴权；
logout 为无状态语义（服务端不维护吊销列表），前端负责清除本地 token；
/auth/me 依赖中间件 JWT 通道挂载的 request.state.user。
"""

import uuid

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel

from exception.bad_except import bad_except
from service.system.auth import AuthService
from utils.response import R

# 创建路由（登录在 /public 下、其余在 /auth 下，故不设统一 prefix）
router = APIRouter(tags=["OpenAPI - 认证"])

_service = AuthService()


class LoginRequest(BaseModel):
    """登录请求体（明文密码，服务端 bcrypt 校验）。"""

    username: str
    password: str


@router.post("/public/auth/login")
async def login(payload: LoginRequest = Body(...)):
    """用户名/密码登录，成功返回 JWT token 与用户基础信息（不含 password）。"""
    data = await _service.login(payload.username, payload.password)
    return R.success(data=data)


@router.post("/auth/logout")
async def logout():
    """登出（无状态语义：服务端不吊销 token，前端清除本地 token 即可）。"""
    return R.success(msg="登出成功")


@router.get("/auth/me")
async def me(request: Request):
    """返回当前 JWT 对应的用户信息（不含 password）。"""
    payload = getattr(request.state, "user", None)
    if payload is None:
        bad_except("当前请求未携带用户登录态")
    user = await _service.me(uuid.UUID(payload["user_id"]))
    return R.success(data=user)
