"""
剧本模块项目域 ORM 模型（映射 story schema 项目聚合相关表）。

项目为聚合根：剧本多版本、关键帧、关键帧出场角色、资产编排（含出演登记）
与导出包；会话/消息/生成任务表结构保留但本阶段未消费。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from entity.base import Base
from utils.date_format import format_datetime
from utils.id import format_id


class StoryProject(Base):
    """
    剧本项目 ORM 模型（映射 story.story_projects）。

    独立实例：归属当前登录用户，仅本人可见；
    冗余计数为列表展示与排序用，业务层增删资产时同步维护。
    """

    __tablename__ = "story_projects"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'新剧本'")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)

    script_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    character_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    art_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    keyframe_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    video_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    generation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_generated_at: Mapped[datetime | None] = mapped_column(nullable=True)

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
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "cover_image": self.cover_image,
            "script_count": self.script_count,
            "character_count": self.character_count,
            "art_count": self.art_count,
            "keyframe_count": self.keyframe_count,
            "video_count": self.video_count,
            "session_count": self.session_count,
            "generation_count": self.generation_count,
            "last_generated_at": format_datetime(self.last_generated_at),
            "status": self.status,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }


class StoryScript(Base):
    """
    剧本资产 ORM 模型（映射 story.story_scripts）。

    多版本并存，version 项目内递增；is_current 为"当前剧本"唯一事实来源，
    业务层切换时先复位再置位。
    """

    __tablename__ = "story_scripts"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ai'")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    generation_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
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
            "project_id": format_id(self.project_id),
            "version": self.version,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "source_message_id": format_id(self.source_message_id),
            "generation_task_id": format_id(self.generation_task_id),
            "is_current": self.is_current,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }


class StoryKeyframe(Base):
    """
    关键帧 ORM 模型（映射 story.story_keyframes）。

    视频生成的视觉锚点：五段式描述 + 正负向提示词 + 参考图 + 最终生成图；
    (project_id, scene_no, shot_no) 唯一，业务层创建前校验冲突。
    """

    __tablename__ = "story_keyframes"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    script_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    chapter_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scene_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shot_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scene_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lighting_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_images: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    image_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generation_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'draft'")
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
            "project_id": format_id(self.project_id),
            "script_id": format_id(self.script_id),
            "chapter_no": self.chapter_no,
            "scene_no": self.scene_no,
            "shot_no": self.shot_no,
            "name": self.name,
            "scene_description": self.scene_description,
            "visual_description": self.visual_description,
            "camera_description": self.camera_description,
            "lighting_description": self.lighting_description,
            "style_description": self.style_description,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "reference_images": self.reference_images,
            "image_file": self.image_file,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "params": self.params,
            "generation_task_id": format_id(self.generation_task_id),
            "status": self.status,
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }


class StoryKeyframeCharacter(Base):
    """
    关键帧出场角色 ORM 模型（映射 story.story_keyframe_characters）。

    (keyframe_id, character_id) 联合主键；记录本镜头使用的参考立绘与
    角色局部描述，角色引用用户级角色库。
    """

    __tablename__ = "story_keyframe_characters"
    __table_args__ = {"schema": "story"}

    keyframe_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    character_art_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    character_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "keyframe_id": format_id(self.keyframe_id),
            "character_id": format_id(self.character_id),
            "character_art_id": format_id(self.character_art_id),
            "role": self.role,
            "character_prompt": self.character_prompt,
            "sequence": self.sequence,
            "created_at": format_datetime(self.created_at),
        }


class StoryProjectAsset(Base):
    """
    项目资产编排 ORM 模型（映射 story.story_project_assets）。

    表达"项目当前要使用"哪些资产：
    - asset_type='character' 为出演登记（引用用户级角色库，引用而非拷贝）；
    - 'character_art' / 'keyframe' / 'script' 表达导出选择与顺序。
    """

    __tablename__ = "story_project_assets"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    is_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE")
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的普通字典，供统一响应回写。"""
        return {
            "id": format_id(self.id),
            "project_id": format_id(self.project_id),
            "asset_type": self.asset_type,
            "asset_id": format_id(self.asset_id),
            "sort_order": self.sort_order,
            "is_selected": self.is_selected,
            "created_at": format_datetime(self.created_at),
        }


class StoryExportPackage(Base):
    """
    导出包 ORM 模型（映射 story.story_export_packages）。

    不可变快照：整理当前剧本 + 出演角色 + 被选关键帧为统一格式
    （不做平台模板），供一键复制到外部视频生成网站。
    """

    __tablename__ = "story_export_packages"
    __table_args__ = {"schema": "story"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuidv7()"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    export_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'video_input'")
    )
    target_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    script_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prompt_text: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    copy_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    def to_dict(self, with_payload: bool = True) -> dict:
        """转为可 JSON 序列化的普通字典。

        列表场景默认携带 payload（快照本体不大且为列表摘要所需）；
        如需裁剪可传 with_payload=False。
        """
        data = {
            "id": format_id(self.id),
            "project_id": format_id(self.project_id),
            "name": self.name,
            "export_type": self.export_type,
            "target_platform": self.target_platform,
            "script_id": format_id(self.script_id),
            "prompt_text": self.prompt_text,
            "copy_text": self.copy_text,
            "markdown_text": self.markdown_text,
            "template_version": self.template_version,
            "version": self.version,
            "created_at": format_datetime(self.created_at),
        }
        if with_payload:
            data["payload"] = self.payload
        return data
