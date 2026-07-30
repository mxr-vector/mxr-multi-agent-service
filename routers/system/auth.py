"""
认证路由（登录 / 登出 / 当前用户 / 个人信息维护）。

登录接口挂 /public/auth/login，天然命中中间件 /public* 白名单免鉴权；
logout 为无状态语义（服务端不维护吊销列表），前端负责清除本地 token；
/auth/me 系列依赖中间件 JWT 通道挂载的 request.state.user。
"""

import asyncio
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Body, File, Request, UploadFile
from pydantic import BaseModel

from exception.bad_except import bad_except
from service.system.auth import AuthService
from utils.env import ENV
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


# 头像允许的图片扩展名与大小上限（2MB，独立于文档上传限额）
_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
_AVATAR_MAX_BYTES = 2 * 1024 * 1024


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


@router.post("/auth/me/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(
        ..., description="头像图片（png/jpg/jpeg/gif/webp，2MB 以内）"
    ),
):
    """上传当前用户头像：存入全局上传目录 avatar/ 下，并覆盖更新 avatar 字段。"""
    user_id = _current_user_id(request)
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _AVATAR_EXTENSIONS:
        bad_except(
            f"不支持的图片类型: {filename or '(无扩展名)'}"
            "（可选 png/jpg/jpeg/gif/webp）"
        )
    data = await file.read()
    # 以实际读到的字节数校验（Content-Length 可伪造）
    if len(data) > _AVATAR_MAX_BYTES:
        bad_except("头像图片超过大小上限（2MB）")

    # 以 user_id 为文件名幂等覆盖；先清理同名异后缀历史头像，避免残留孤儿文件
    avatar_dir = ENV.upload_dir / "avatar"
    stem = user_id.hex

    def _save() -> None:
        avatar_dir.mkdir(parents=True, exist_ok=True)
        for old in avatar_dir.glob(f"{stem}.*"):
            old.unlink(missing_ok=True)
        (avatar_dir / f"{stem}.{ext}").write_bytes(data)

    # 同步磁盘 IO 统一用 to_thread 包装，不阻塞事件循环
    await asyncio.to_thread(_save)
    # 存相对路径（不含 BASE_URL，由前端补代理前缀）；
    # 时间戳查询串破除同名覆盖场景的浏览器缓存
    avatar_url = f"/public/files/avatar/{stem}.{ext}?v={int(time.time())}"
    user = await _service.update_profile(user_id, avatar=avatar_url)
    return R.success(data=user)
