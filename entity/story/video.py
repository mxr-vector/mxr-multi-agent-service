"""
剧本模块视频成品域 ORM 模型（映射 story.story_videos）。

视频成品为外部视频网站生成的单镜头片段，由用户手动上传回收登记；
系统不做视频生成，也不建模整集装配。
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class StoryVideo(Base):
    """
    视频成品 ORM 模型（映射 story.story_videos）。

    keyframe_id 为主溯源轴（一帧可多条重抽），script_id / export_package_id
    并列溯源；episode_no 语义放宽为可选分组/排序号；
    cover_file 默认抽视频首帧，失败留空可手动上传。
    """

    __tablename__ = "story_videos"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    keyframe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    script_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    export_package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    episode_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_file: Mapped[str] = mapped_column(String(500), nullable=False)
    cover_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'done'")
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

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
            "project_id": format_id(self.project_id),
            "keyframe_id": format_id(self.keyframe_id),
            "script_id": format_id(self.script_id),
            "export_package_id": format_id(self.export_package_id),
            "title": self.title,
            "episode_no": self.episode_no,
            "video_file": self.video_file,
            "cover_file": self.cover_file,
            "duration_ms": self.duration_ms,
            "file_size": self.file_size,
            "width": self.width,
            "height": self.height,
            "target_platform": self.target_platform,
            "external_task_id": self.external_task_id,
            "status": self.status,
            "remark": self.remark,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }
