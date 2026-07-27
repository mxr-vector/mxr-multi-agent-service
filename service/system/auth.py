"""
认证业务层（登录 / 当前用户）。

登录失败语义（防用户枚举）：用户名不存在与密码错误 MUST 返回同一文案；
status='disabled' 的用户拒绝登录并明确提示。均走 bad_except 统一失败响应。
"""

import uuid

from database.postgre_client import get_session
from database.system.user import UserRepository
from exception.bad_except import bad_except
from service.system.password import verify_password
from utils.id import format_id
from utils.jwt_token import create_token
from utils.user_context import aggregate_data_scope

# 用户名不存在与密码错误共用文案，防止用户枚举
_LOGIN_FAILED_MSG = "用户名或密码错误"


class AuthService:
    """认证业务层：bcrypt 校验密码、签发 JWT、查询当前用户信息。"""

    async def login(self, username: str, password: str) -> dict:
        """
        用户名/密码登录：校验通过后签发 JWT，返回 token 与基础用户信息（不含 password）。
        """
        async with get_session() as session:
            user = await UserRepository(session).get_by_username(username)
            if user is None or not verify_password(password, user.password):
                bad_except(_LOGIN_FAILED_MSG)
            if user.status == "disabled":
                bad_except("账号已停用，请联系管理员")
            token = create_token(format_id(user.id), user.username)
            return {"token": token, "user": user.to_dict()}

    async def me(self, user_id: uuid.UUID) -> dict:
        """按 JWT 中的 user_id 返回当前用户信息（不含 password），附聚合 data_scope。"""
        async with get_session() as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                bad_except("用户不存在或已被删除")
            data = user.to_dict()
            # 聚合有效角色的最宽 data_scope，前端据此决定部门树筛选入口可见性
            data["data_scope"] = await aggregate_data_scope(session, user_id)
            return data
