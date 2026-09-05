import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from utils.env import ENV
from utils.jwt_token import verify_token

# 可配置无需认证的路径
EXCLUDE_PATHS = {"/", "/docs", "/openapi.json", "/favicon.ico", "/static"}


def _is_excluded(path: str) -> bool:
    """免鉴权判定：静态路径集合 + mount 型前缀。

    - 前缀统一按路径段匹配（/public 或 /public/...），防止 /publicxxx 误免鉴权；
    - /static 为 mount 前缀，静态资源实际路径形如 /static/assets/xxx.js，
      精确匹配集合无法命中，须按前缀放行。
    """
    if path in EXCLUDE_PATHS:
        return True
    return path == "/public" or path.startswith("/public/") or path.startswith(
        "/static/"
    )


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

        # 跳过无需认证的路径（含 BASE_URL 挂载前缀下的 /public，按路径段匹配）
        base_public = f"{ENV.base_url}/public"
        if _is_excluded(path) or path == base_public or path.startswith(
            base_public + "/"
        ):
            return await call_next(request)

        auth = request.headers.get("Authorization")

        # 通道一：静态 API key（机器调用），常数时间比对防时序侧信道。
        # 以 bytes 比对：str 版 compare_digest 遇非 ASCII 头值会抛 TypeError，
        # 且异常发生在中间件层、统一异常处理器接不住，会把 401 变成裸 500
        if auth is not None and hmac.compare_digest(
            auth.encode("utf-8", "surrogateescape"),
            f"Bearer {ENV.api_secret_key}".encode("utf-8", "surrogateescape"),
        ):
            return await call_next(request)

        # 通道二：JWT（用户登录态）；RFC 7235 规定 auth-scheme 大小写不敏感，
        # "bearer <jwt>" 与 "Bearer <jwt>" 等价（静态 key 通道仍整串精确比对不放宽）
        if auth:
            scheme, _, token = auth.partition(" ")
            if scheme.lower() == "bearer" and token:
                payload = verify_token(token)
                if payload is not None:
                    request.state.user = payload
                    return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"code": 401, "msg": "Invalid or missing token", "data": None},
        )
