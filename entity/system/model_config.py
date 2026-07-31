import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class ModelConfig(Base):
    """
    模型配置 ORM 模型（映射 sys_model_config）。

    - 每行对应一个模型角色（chat/rewrite/visual/rerank），role 全局唯一，
      前端以一行渲染为一张配置卡片；
    - api_key 落盘明文，掩码仅在 service 层做（to_dict 返回原值，禁止直接对外）；
    - provider 目前仅 rerank 使用；timeout/max_retries 目前 chat/visual 使用；
      extra 为角色特有参数兜底；
    - is_builtin 为内置行删除保护标记，禁删但允许更新其余字段；
    - updated_at 由业务层在更新时显式赋值，不依赖数据库触发器。
    """

    __tablename__ = "sys_model_config"
    __table_args__ = {"schema": "sys"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_window: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("200000")
    )
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典（api_key 为原值，掩码由 service 层处理）。"""
        return {
            "id": format_id(self.id),
            "role": self.role,
            "name": self.name,
            "model_name": self.model_name,
            "api_url": self.api_url,
            "api_key": self.api_key,
            "provider": self.provider,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "context_window": self.context_window,
            "extra": self.extra,
            "is_builtin": self.is_builtin,
            "remark": self.remark,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
