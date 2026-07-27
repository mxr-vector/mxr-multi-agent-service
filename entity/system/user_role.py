import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.id import format_id


class UserRole(Base):
    """
    用户-角色关联 ORM 模型（映射 sys_user_role，N:M 中间表）。

    - (user_id, role_id) 联合主键，无独立 id 列；
    - 分配采用全量覆盖语义：先按 user_id 清空再批量插入，同一事务内完成；
    - user_id/role_id 为逻辑关联，存在性由业务层保证。
    """

    __tablename__ = "sys_user_role"
    __table_args__ = {"schema": "sys"}

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "user_id": format_id(self.user_id),
            "role_id": format_id(self.role_id),
        }
