import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from utils.env import ENV
from utils.jwt_token import verify_token

# 可配置无需认证的路径
EXCLUDE_PATHS = {"/", "/docs", "/openapi.json", "/favicon.ico", "/static"}


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """
    双通道鉴权：
    1. 静态通道（机器调用）：Bearer <API_SECRET_KEY> 精确比对，O(1) 快路径；
    2. JWT 通道（用户登录态）：静态 key 不匹配时尝试 JWT decode，
       验证通过后将 payload 挂到 request.state.user 供下游读取。
    两者皆不满足返回 401 统一响应体。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 跳过无需认证的路径（/public* 同时兼容 BASE_URL 挂载前缀）
        if (
            path in EXCLUDE_PATHS
            or path.startswith("/public")
            or path.startswith(f"{ENV.base_url}/public")
        ):
            return await call_next(request)

        auth = request.headers.get("Authorization")

        # 通道一：静态 API key（机器调用），常数时间比对防时序侧信道
        if auth is not None and hmac.compare_digest(
            auth, f"Bearer {ENV.api_secret_key}"
        ):
            return await call_next(request)

        # 通道二：JWT（用户登录态）
        if auth and auth.startswith("Bearer "):
            payload = verify_token(auth[7:])
            if payload is not None:
                request.state.user = payload
                return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"code": 401, "msg": "Invalid or missing token", "data": None},
        )
