"""
剧本模块视频成品域持久层（DAO）。

写操作只 flush 不 commit，事务原子性由 service 层统一保证
（对齐 database/draw/diagram.py 的 Repository 约定）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from entity.story.video import StoryVideo
from utils.page import paginate

# 生成中任务状态（启动清扫与互斥判定共用口径）
RUNNING_STATUSES = ("queued", "generating")

# 集间衔接片段在 generation_params.kind 上的标记（默认列表与互斥判定需排除）
TRANSITION_KIND = "transition"


def _not_transition():
    """排除集间衔接片段的 SQL 条件（JSONB kind 为空视为普通章节片段）。"""
    return func.coalesce(StoryVideo.generation_params["kind"].astext, "") != TRANSITION_KIND


class VideoRepository:
    """视频成品持久层：项目维度登记、关键帧反查与维护。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        video_id: uuid.UUID,
        project_id: uuid.UUID,
        video_file: str | None = None,
        keyframe_id: uuid.UUID | None = None,
        script_id: uuid.UUID | None = None,
        export_package_id: uuid.UUID | None = None,
        source: str = "upload",
        title: str | None = None,
        episode_no: int | None = None,
        cover_file: str | None = None,
        duration_ms: int | None = None,
        file_size: int | None = None,
        width: int | None = None,
        height: int | None = None,
        prompt: str | None = None,
        negative_prompt: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        generation_params: dict | None = None,
        target_platform: str | None = None,
        external_task_id: str | None = None,
        status: str = "done",
        error_message: str | None = None,
        remark: str | None = None,
    ) -> StoryVideo:
        """插入视频登记；id 由应用端生成。"""
        video = StoryVideo(
            id=video_id,
            project_id=project_id,
            keyframe_id=keyframe_id,
            script_id=script_id,
            export_package_id=export_package_id,
            source=source,
            title=title,
            episode_no=episode_no,
            video_file=video_file,
            cover_file=cover_file,
            duration_ms=duration_ms,
            file_size=file_size,
            width=width,
            height=height,
            prompt=prompt,
            negative_prompt=negative_prompt,
            provider=provider,
            model=model,
            generation_params=generation_params,
            target_platform=target_platform,
            external_task_id=external_task_id,
            status=status,
            error_message=error_message,
            remark=remark,
        )
        self.session.add(video)
        await self.session.flush()
        return video

    async def get(self, video_id: uuid.UUID) -> StoryVideo | None:
        """按 id 获取视频登记。"""
        return await self.session.get(StoryVideo, video_id)

    async def list(
        self,
        project_id: uuid.UUID,
        keyframe_id: uuid.UUID | None = None,
        page: int = 1,
        size: int = 20,
        source: str | None = None,
        status: str | None = None,
    ) -> tuple[list[StoryVideo], int]:
        """按项目分页列出视频（可按关键帧/来源/状态过滤），创建时间倒序。

        默认排除集间衔接片段：它们只在「关联集」视图展示，避免污染成品列表
        与按集取最新片段的判定。
        """
        stmt = select(StoryVideo).where(
            StoryVideo.project_id == project_id,
            _not_transition(),
        )
        if keyframe_id is not None:
            stmt = stmt.where(StoryVideo.keyframe_id == keyframe_id)
        if source is not None:
            stmt = stmt.where(StoryVideo.source == source)
        if status is not None:
            stmt = stmt.where(StoryVideo.status == status)
        stmt = stmt.order_by(StoryVideo.created_at.desc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def list_by_keyframe(self, keyframe_id: uuid.UUID) -> "list[StoryVideo]":
        """按关键帧反查全部生成片段（创建时间升序）。"""
        stmt = (
            select(StoryVideo)
            .where(StoryVideo.keyframe_id == keyframe_id)
            .order_by(StoryVideo.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_generated(self, project_id: uuid.UUID) -> "list[StoryVideo]":
        """列出项目全部生成片段（含衔接片段），创建时间升序。"""
        stmt = (
            select(StoryVideo)
            .where(
                StoryVideo.project_id == project_id,
                StoryVideo.source == "generated",
            )
            .order_by(StoryVideo.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def has_active_for_episode(
        self, project_id: uuid.UUID, episode_no: int
    ) -> bool:
        """同一章节是否已有在途片段生成任务（衔接片段不计入章节互斥）。"""
        stmt = (
            select(StoryVideo.id)
            .where(
                StoryVideo.project_id == project_id,
                StoryVideo.episode_no == episode_no,
                StoryVideo.source == "generated",
                StoryVideo.status.in_(RUNNING_STATUSES),
                _not_transition(),
            )
            .limit(1)
        )
        return await self.session.scalar(stmt) is not None

    async def update_fields(self, video: StoryVideo, fields: dict) -> StoryVideo:
        """按传入字段局部更新并刷新 updated_at。"""
        for key, value in fields.items():
            setattr(video, key, value)
        video.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return video

    async def reset_stale_generating(self) -> int:
        """全库残留 queued/generating 的视频统一置为 failed（启动清扫崩溃恢复路径）。"""
        stmt = (
            update(StoryVideo)
            .where(StoryVideo.status.in_(RUNNING_STATUSES))
            .values(
                status="failed",
                error_message="服务重启，生成任务已中断",
                updated_at=datetime.now(timezone.utc),
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def delete(self, video: StoryVideo) -> None:
        """物理删除视频登记（不级联溯源对象）。"""
        await self.session.delete(video)
        await self.session.flush()

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        """项目视频数（供冗余计数对账）。"""
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(StoryVideo)
                .where(StoryVideo.project_id == project_id)
            )
            or 0
        )
