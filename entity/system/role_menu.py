import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.id import format_id


class RoleMenu(Base):
    """
    角色-菜单关联 ORM 模型（映射 sys_role_menu，N:M 中间表）。

    - (role_id, menu_id) 联合主键，无独立 id 列；
    - 分配采用全量覆盖语义：先按 role_id 清空再批量插入，同一事务内完成；
    - role_id/menu_id 为逻辑关联，存在性由业务层保证。
    """

    __tablename__ = "sys_role_menu"
    __table_args__ = {"schema": "sys"}

    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    menu_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "role_id": format_id(self.role_id),
            "menu_id": format_id(self.menu_id),
        }
