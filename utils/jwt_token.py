"""
jwt_token.py - JWT 签发与验证工具（HS256）

签名密钥使用独立的 JWT_SECRET_KEY（经 ENV 暴露），与对外分发的
API_SECRET_KEY 严格分离；payload 固定携带 user_id / username / exp。
过期或签名无效均视为未认证，返回 None 由调用方决定后续处理。
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from utils.env import ENV

_ALGORITHM = "HS256"


def create_token(user_id: str, username: str) -> str:
    """签发 JWT：payload 含 user_id（32 位 hex）、username、exp。"""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "username": username,
        "iat": now,
        "exp": now + timedelta(hours=ENV.jwt_expire_hours),
    }
    return jwt.encode(payload, ENV.jwt_secret_key, algorithm=_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """
    验证 JWT，返回 payload dict；过期 / 签名无效 / 结构非法均返回 None。
    """
    try:
        return jwt.decode(
            token,
            ENV.jwt_secret_key,
            algorithms=[_ALGORITHM],
            # 强制要求 exp：缺失过期时间的 token 一律拒绝（算法钉死 HS256 不变）
            options={"require": ["exp"]},
        )
    except jwt.InvalidTokenError:
        return None
