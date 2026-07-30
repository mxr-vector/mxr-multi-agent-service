"""
认证路由（登录 / 登出 / 当前用户 / 个人信息维护）。

登录接口挂 /public/auth/login，天然命中中间件 /public* 白名单免鉴权；
logout 为无状态语义（服务端不维护吊销列表），前端负责清除本地 token；
/auth/me 系列依赖中间件 JWT 通道挂载的 request.state.user。
"""

import uuid
from typing import Optional

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


class ProfileUpdate(BaseModel):
    """个人资料更新请求体（仅本人可维护字段，username/status 等管理字段不开放）。"""

    nickname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None


class PasswordChange(BaseModel):
    """修改自己密码请求体（需校验原密码，区别于管理员重置密码）。"""

    old_password: str
    new_password: str


def _current_user_id(request: Request) -> uuid.UUID:
    """从中间件 JWT 通道挂载的 payload 中取当前用户 id，机器通道无登录态则拒绝。"""
    payload = getattr(request.state, "user", None)
    if payload is None:
        bad_except("当前请求未携带用户登录态")
    return uuid.UUID(payload["user_id"])


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
    user = await _service.me(_current_user_id(request))
    return R.success(data=user)


@router.put("/auth/me")
async def update_profile(request: Request, payload: ProfileUpdate = Body(...)):
    """更新当前用户个人资料（昵称/邮箱/手机/头像），返回更新后的用户信息。"""
    user = await _service.update_profile(
        _current_user_id(request),
        nickname=payload.nickname,
        email=payload.email,
        phone=payload.phone,
        avatar=payload.avatar,
    )
    return R.success(data=user)


@router.put("/auth/me/password")
async def change_password(request: Request, payload: PasswordChange = Body(...)):
    """修改当前用户密码（先校验原密码，再 bcrypt 哈希新密码覆盖）。"""
    await _service.change_password(
        _current_user_id(request), payload.old_password, payload.new_password
    )
    return R.success(msg="密码修改成功")
