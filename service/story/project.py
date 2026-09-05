"""
剧本模块项目业务层：项目 CRUD、软删与冗余计数同步。

冗余计数统一走"事务内重算"（ProjectRepository.recount_assets），口径与
统计视图 story_project_asset_stats 一致，避免增量维护漂移；项目改名时
迁移其关键帧图片目录（按 项目名/关键帧名 组织）。
"""

import asyncio
import uuid
from datetime import datetime, timezone

from uuid_utils.compat import uuid7

from agent.constants.enums.story import StoryProjectStatus
from database.postgre_client import get_session
from database.story.project import (
    KeyframeRepository,
    ProjectRepository,
    ScriptRepository,
)
from exception.bad_except import bad_except
from service.story.storage import (
    KEYFRAME_IMAGE_ROOT,
    assert_asset_relative,
    keyframe_image_dir,
    move_without_overwrite,
    resolve_upload_path,
    sanitize_dir_name,
)
from utils.date_format import format_datetime
from utils.env import ENV
from utils.id import format_id
from utils.logger import logger

# 项目状态白名单（业务层校验，数据库无 CHECK）
_PROJECT_STATUS = frozenset(
    s.value for s in StoryProjectStatus if s != StoryProjectStatus.DELETED
)

# 项目可更新字段白名单
_PROJECT_UPDATABLE = {"title", "description", "cover_image", "status"}

# 标题长度上限：title 列为 TEXT 无界，但导出包自动命名落 VARCHAR(200)，
# 服务端统一限制标题长度，防止超长标题令项目永久不可导出
_PROJECT_TITLE_MAX = 180


def _assert_user_channel(ctx) -> None:
    """项目管理仅支持用户通道调用（机器通道无属主概念）。"""
    if not ctx.user_id:
        bad_except("项目管理仅支持用户通道调用")


class ProjectService:
    """项目业务层：属主校验收口 + 软删。"""

    async def _assert_owned(self, session, project_id: uuid.UUID, ctx):
        """项目须存在、未删除且归属当前用户。"""
        project = await ProjectRepository(session).get(project_id)
        if (
            project is None
            or project.status == StoryProjectStatus.DELETED
            or project.user_id != ctx.user_id
        ):
            bad_except("项目不存在")
        return project

    async def list(
        self,
        ctx,
        page: int,
        size: int,
        keyword: str | None = None,
        status: str | None = None,
    ):
        """分页列出本人项目，更新时间倒序。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            items, total = await ProjectRepository(session).list(
                ctx.user_id, page, size, keyword, status
            )
            return [item.to_dict() for item in items], total

    async def create(self, ctx, payload) -> dict:
        """创建项目（标题缺省"新剧本"）。"""
        _assert_user_channel(ctx)
        title = (payload.title or "").strip() or "新剧本"
        if len(title) > _PROJECT_TITLE_MAX:
            bad_except(f"项目标题不能超过 {_PROJECT_TITLE_MAX} 字符")
        async with get_session() as session:
            project = await ProjectRepository(session).create(
                project_id=uuid7(),
                user_id=ctx.user_id,
                title=title,
                description=payload.description,
            )
            await session.commit()
            return project.to_dict()

    async def detail(self, ctx, project_id: uuid.UUID) -> dict:
        """项目详情：本体 + 当前剧本摘要。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            project = await self._assert_owned(session, project_id, ctx)
            current_script = await ScriptRepository(session).get_current(project_id)
            data = project.to_dict()
            data["current_script"] = (
                {
                    "id": format_id(current_script.id),
                    "version": current_script.version,
                    "title": current_script.title,
                    "updated_at": format_datetime(current_script.updated_at),
                }
                if current_script
                else None
            )
            return data

    async def update(self, ctx, project_id: uuid.UUID, payload) -> dict:
        """局部更新项目字段（白名单内显式传入的字段）。"""
        _assert_user_channel(ctx)
        fields = {
            key: value
            for key, value in payload.model_dump(exclude_unset=True).items()
            if key in _PROJECT_UPDATABLE
        }
        if not fields:
            bad_except("没有可更新的字段")
        if "title" in fields:
            fields["title"] = (fields["title"] or "").strip()
            if not fields["title"]:
                bad_except("项目标题不能为空")
            if len(fields["title"]) > _PROJECT_TITLE_MAX:
                bad_except(f"项目标题不能超过 {_PROJECT_TITLE_MAX} 字符")
        if "cover_image" in fields:
            assert_asset_relative(fields["cover_image"], ("story/",))
        if "status" in fields and fields["status"] not in _PROJECT_STATUS:
            bad_except(f"项目状态非法: {fields['status']}")
        async with get_session() as session:
            project = await self._assert_owned(session, project_id, ctx)
            old_title = project.title
            await ProjectRepository(session).update_fields(project, fields)
            moved: list[tuple[str, str]] = []
            if "title" in fields and fields["title"] != old_title:
                moved = await self._relocate_keyframe_images(
                    session, project, old_title
                )
            try:
                await session.commit()
            except Exception:
                # commit 失败：DB 路径已回滚，已迁移的文件须搬回原位，否则图片 404
                if moved:
                    await self._rollback_keyframe_moves(moved)
                raise
            return project.to_dict()

    async def _relocate_keyframe_images(
        self, session, project, old_title: str
    ) -> "list[tuple[str, str]]":
        """项目改名后把全部关键帧图片从旧项目名目录迁至新目录并同步路径。

        仅重写路径中「项目名」那一段（规范布局 story/keyframes/<项目名>/…），
        不触碰关键帧名段的同名目录；move 采用不覆盖语义，目标已存在即跳过。
        单文件缺失/迁移失败保留原路径、不阻断改名，仅记录告警。

        返回已完成迁移的 (新相对路径, 旧相对路径) 列表，供 commit 失败时回滚。
        """
        keyframes = await KeyframeRepository(session).list_with_images(project.id)
        if not keyframes:
            return []
        old_project_dir = sanitize_dir_name(old_title, project.id.hex)
        new_project_dir = sanitize_dir_name(project.title, project.id.hex)
        if old_project_dir == new_project_dir:
            return []
        old_prefix = f"{KEYFRAME_IMAGE_ROOT}/{old_project_dir}/"
        new_prefix = f"{KEYFRAME_IMAGE_ROOT}/{new_project_dir}/"
        base = ENV.upload_dir

        def _move_all() -> list[tuple[str, str]]:
            moved: list[tuple[str, str]] = []
            for keyframe in keyframes:
                image_file = keyframe.image_file
                # 仅迁移规范布局（项目名段精确匹配）下的图片，防误改关键帧名段
                if not image_file or not image_file.startswith(old_prefix):
                    continue
                try:
                    src = resolve_upload_path(image_file)
                except Exception:
                    logger.warning(
                        f"[STORY] 关键帧图片路径非法，跳过迁移: {image_file}"
                    )
                    continue
                if not src.is_file():
                    logger.warning(f"[STORY] 关键帧图片缺失，跳过迁移: {image_file}")
                    continue
                new_rel = new_prefix + image_file[len(old_prefix) :]
                dst = base / new_rel
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    move_without_overwrite(src, dst)
                except FileExistsError:
                    logger.warning(
                        f"[STORY] 关键帧图片迁移目标已存在，跳过不覆盖: {new_rel}"
                    )
                    continue
                except OSError as exc:
                    logger.warning(f"[STORY] 关键帧图片迁移失败: {image_file}: {exc}")
                    continue
                moved.append((new_rel, image_file))
            return moved

        moved = await asyncio.to_thread(_move_all)
        if not moved:
            return []
        new_by_old = {old: new for new, old in moved}
        for keyframe in keyframes:
            new_rel = new_by_old.get(keyframe.image_file)
            if new_rel:
                keyframe.image_file = new_rel
                keyframe.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return moved

    async def _rollback_keyframe_moves(self, moved: "list[tuple[str, str]]") -> None:
        """commit 失败后把已迁移的关键帧图片搬回原位（新→旧），失败仅告警。"""
        base = ENV.upload_dir

        def _rollback() -> None:
            for new_rel, old_rel in moved:
                try:
                    src = base / new_rel
                    if not src.is_file():
                        continue
                    dst = base / old_rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    move_without_overwrite(src, dst)
                except OSError as exc:
                    logger.warning(
                        f"[STORY] 关键帧图片回滚失败: {new_rel} -> {old_rel}: {exc}"
                    )

        await asyncio.to_thread(_rollback)

    async def delete(self, ctx, project_id: uuid.UUID) -> None:
        """软删项目（状态置 deleted，列表不可见；资产行保留不追删）。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            project = await self._assert_owned(session, project_id, ctx)
            await ProjectRepository(session).update_fields(
                project, {"status": StoryProjectStatus.DELETED}
            )
            await session.commit()
