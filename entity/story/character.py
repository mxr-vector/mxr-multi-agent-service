"""
剧本模块角色域 ORM 模型（映射 story schema 角色库两张表）。

角色库归属用户（仅本人可见），可被多个项目复用；立绘随角色归属用户，
项目维度经出演登记（story_project_assets）展开。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class StoryCharacter(Base):
    """
    角色 ORM 模型（映射 story.story_characters）。

    - user_id 为属主（32 位无连字符 hex），角色仅本人可见；
    - profile 结构化人设 / style 视觉风格（JSONB），供剧本/生图复用；
    - art_count 冗余立绘数，业务层增删立绘时同步维护。
    """

    __tablename__ = "story_characters"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profile: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    style: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    appearance_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    art_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
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
            "user_id": self.user_id,
            "name": self.name,
            "role_type": self.role_type,
            "profile": self.profile,
            "style": self.style,
            "appearance_prompt": self.appearance_prompt,
            "negative_prompt": self.negative_prompt,
            "avatar_file": self.avatar_file,
            "art_count": self.art_count,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }


class StoryCharacterArt(Base):
    """
    角色立绘 ORM 模型（映射 story.story_character_arts）。

    立绘随角色归属用户；is_primary 为角色主立绘（业务层切换时先复位再置位）；
    source 区分 upload / ai，AI 生成记录提示词以便再生成。
    """

    __tablename__ = "story_character_arts"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_file: Mapped[str] = mapped_column(String(500), nullable=False)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    art_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'full_body'")
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'upload'")
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generation_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'done'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

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
            "character_id": format_id(self.character_id),
            "name": self.name,
            "image_file": self.image_file,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "art_type": self.art_type,
            "source": self.source,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "params": self.params,
            "generation_task_id": format_id(self.generation_task_id),
            "is_primary": self.is_primary,
            "status": self.status,
            "error": self.error,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
