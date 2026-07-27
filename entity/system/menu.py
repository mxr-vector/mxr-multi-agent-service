import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class Menu(Base):
    """
    菜单树 ORM 模型（映射 sys_menu）。

    - parent_id 自引用，NULL 表示顶级节点，存在性与防环由业务层保证；
    - menu_type 三种类型：'dir' 目录（仅组织层级）、'menu' 页面菜单
      （path/name/component 对应前端路由）、'button' 按钮权限项（仅 perms
      有意义），取值由业务层校验；
    - component 存前端组件键（如 'system-user'），由前端 viewModules 映射；
    - perms 本阶段仅存储，不参与鉴权；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "sys_menu"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    menu_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    component: Mapped[str | None] = mapped_column(String(100), nullable=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    perms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "id": format_id(self.id),
            "parent_id": format_id(self.parent_id),
            "menu_type": self.menu_type,
            "name": self.name,
            "path": self.path,
            "component": self.component,
            "label": self.label,
            "icon": self.icon,
            "perms": self.perms,
            "visible": self.visible,
            "sort_order": self.sort_order,
            "status": self.status,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
