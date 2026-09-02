"""
剧本模块视频成品域持久层（DAO）。

写操作只 flush 不 commit，事务原子性由 service 层统一保证
（对齐 database/draw/diagram.py 的 Repository 约定）。
"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from entity.story.video import StoryVideo
from utils.page import paginate


class VideoRepository:
    """视频成品持久层：项目维度登记、关键帧反查与维护。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        video_id: uuid.UUID,
        project_id: uuid.UUID,
        video_file: str,
        keyframe_id: uuid.UUID | None = None,
        script_id: uuid.UUID | None = None,
        export_package_id: uuid.UUID | None = None,
        title: str | None = None,
        episode_no: int | None = None,
        cover_file: str | None = None,
        duration_ms: int | None = None,
        file_size: int | None = None,
        width: int | None = None,
        height: int | None = None,
        target_platform: str | None = None,
        external_task_id: str | None = None,
        remark: str | None = None,
    ) -> StoryVideo:
        """插入视频登记；id 由应用端生成。"""
        video = StoryVideo(
            id=video_id,
            project_id=project_id,
            keyframe_id=keyframe_id,
            script_id=script_id,
            export_package_id=export_package_id,
            title=title,
            episode_no=episode_no,
            video_file=video_file,
            cover_file=cover_file,
            duration_ms=duration_ms,
            file_size=file_size,
            width=width,
            height=height,
            target_platform=target_platform,
            external_task_id=external_task_id,
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
    ) -> tuple[list[StoryVideo], int]:
        """按项目分页列出视频（可选按关键帧过滤），创建时间倒序。"""
        stmt = select(StoryVideo).where(StoryVideo.project_id == project_id)
        if keyframe_id is not None:
            stmt = stmt.where(StoryVideo.keyframe_id == keyframe_id)
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

    async def update_fields(self, video: StoryVideo, fields: dict) -> StoryVideo:
        """按传入字段局部更新并刷新 updated_at。"""
        from datetime import datetime, timezone

        for key, value in fields.items():
            setattr(video, key, value)
        video.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return video

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
