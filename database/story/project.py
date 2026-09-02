"""
剧本模块项目域持久层（DAO）。

项目为聚合根：项目本体、剧本多版本、关键帧与出场角色、资产编排（含出演
登记）、导出包。写操作只 flush 不 commit，事务原子性由 service 层统一保证
（对齐 database/draw/diagram.py 的 Repository 约定）。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from entity.story.project import (
    StoryExportPackage,
    StoryKeyframe,
    StoryKeyframeCharacter,
    StoryProject,
    StoryProjectAsset,
    StoryScript,
)
from utils.page import paginate


class ProjectRepository:
    """项目持久层：按属主收敛的 CRUD、软删与冗余计数重算。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        project_id: uuid.UUID,
        user_id: str,
        title: str = "新剧本",
        description: str | None = None,
    ) -> StoryProject:
        """插入项目；id 由应用端生成。"""
        project = StoryProject(
            id=project_id,
            user_id=user_id,
            title=title,
            description=description,
        )
        self.session.add(project)
        await self.session.flush()
        return project

    async def get(self, project_id: uuid.UUID) -> StoryProject | None:
        """按 id 获取项目（含软删行，由业务层决定语义）。"""
        return await self.session.get(StoryProject, project_id)

    async def get_for_update(self, project_id: uuid.UUID) -> StoryProject | None:
        """按 id 获取项目并加行锁（SELECT ... FOR UPDATE）。

        用于剧本版本号分配等读-改-写场景，串行化同项目并发请求，
        防止 UNIQUE(project_id, version) 冲突。
        """
        stmt = (
            select(StoryProject).where(StoryProject.id == project_id).with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list(
        self,
        user_id: str,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[StoryProject], int]:
        """按属主分页列出项目（标题模糊检索），更新时间倒序。

        status 缺省过滤掉软删行；显式传值按值过滤。
        """
        stmt = select(StoryProject).where(StoryProject.user_id == user_id)
        if status:
            stmt = stmt.where(StoryProject.status == status)
        else:
            stmt = stmt.where(StoryProject.status != "deleted")
        if keyword:
            stmt = stmt.where(StoryProject.title.ilike(f"%{keyword}%"))
        stmt = stmt.order_by(StoryProject.updated_at.desc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def update_fields(self, project: StoryProject, fields: dict) -> StoryProject:
        """按传入字段局部更新并刷新 updated_at。"""
        for key, value in fields.items():
            setattr(project, key, value)
        project.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return project

    async def recount_assets(self, project: StoryProject) -> StoryProject:
        """按资产表真实数量重算冗余计数（与统计视图口径一致）。

        剧本数按剧本表；角色数/立绘数按编排表（出演登记/选中立绘）；
        关键帧数排除 archived；视频数按视频表。
        """
        project_id = project.id
        project.script_count = (
            await self.session.scalar(
                select(func.count())
                .select_from(StoryScript)
                .where(StoryScript.project_id == project_id)
            )
            or 0
        )
        asset_rows = (
            await self.session.execute(
                select(StoryProjectAsset.asset_type, func.count())
                .where(StoryProjectAsset.project_id == project_id)
                .group_by(StoryProjectAsset.asset_type)
            )
        ).all()
        asset_counts = {row[0]: row[1] for row in asset_rows}
        project.character_count = asset_counts.get("character", 0)
        project.art_count = asset_counts.get("character_art", 0)
        project.keyframe_count = (
            await self.session.scalar(
                select(func.count())
                .select_from(StoryKeyframe)
                .where(
                    StoryKeyframe.project_id == project_id,
                    StoryKeyframe.status != "archived",
                )
            )
            or 0
        )
        from entity.story.video import StoryVideo

        project.video_count = (
            await self.session.scalar(
                select(func.count())
                .select_from(StoryVideo)
                .where(StoryVideo.project_id == project_id)
            )
            or 0
        )
        project.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return project


class ScriptRepository:
    """剧本持久层：多版本追加、当前版本单点切换（先复位再置位）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_version(self, project_id: uuid.UUID) -> int:
        """项目内下一个版本号（当前最大 + 1，从 1 开始）。"""
        current = await self.session.scalar(
            select(func.max(StoryScript.version)).where(
                StoryScript.project_id == project_id
            )
        )
        return (current or 0) + 1

    async def create(
        self,
        script_id: uuid.UUID,
        project_id: uuid.UUID,
        version: int,
        content: str,
        title: str | None = None,
        source: str = "user",
        source_message_id: uuid.UUID | None = None,
        generation_task_id: uuid.UUID | None = None,
        is_current: bool = False,
    ) -> StoryScript:
        """插入剧本版本；id 由应用端生成。"""
        script = StoryScript(
            id=script_id,
            project_id=project_id,
            version=version,
            title=title,
            content=content,
            source=source,
            source_message_id=source_message_id,
            generation_task_id=generation_task_id,
            is_current=is_current,
        )
        self.session.add(script)
        await self.session.flush()
        return script

    async def get(self, script_id: uuid.UUID) -> StoryScript | None:
        """按 id 获取剧本。"""
        return await self.session.get(StoryScript, script_id)

    async def list_by_project(
        self, project_id: uuid.UUID, page: int = 1, size: int = 50
    ) -> tuple[list[StoryScript], int]:
        """按项目分页列出剧本，版本号倒序。"""
        stmt = (
            select(StoryScript)
            .where(StoryScript.project_id == project_id)
            .order_by(StoryScript.version.desc())
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get_current(self, project_id: uuid.UUID) -> StoryScript | None:
        """项目当前剧本（is_current 单点）。"""
        stmt = select(StoryScript).where(
            StoryScript.project_id == project_id,
            StoryScript.is_current.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def clear_current(self, project_id: uuid.UUID) -> int:
        """复位项目全部剧本的当前标记（切换前置位前的复位步），返回影响行数。"""
        stmt = (
            update(StoryScript)
            .where(
                StoryScript.project_id == project_id,
                StoryScript.is_current.is_(True),
            )
            .values(is_current=False, updated_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def update_fields(self, script: StoryScript, fields: dict) -> StoryScript:
        """按传入字段局部更新并刷新 updated_at。"""
        for key, value in fields.items():
            setattr(script, key, value)
        script.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return script


class KeyframeRepository:
    """关键帧持久层：项目维度 CRUD 与（场景号, 镜头号）冲突检测。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        keyframe_id: uuid.UUID,
        project_id: uuid.UUID,
        prompt: str,
        **fields,
    ) -> StoryKeyframe:
        """插入关键帧；id 由应用端生成，其余字段按 schema 默认。"""
        keyframe = StoryKeyframe(
            id=keyframe_id,
            project_id=project_id,
            prompt=prompt,
            **fields,
        )
        self.session.add(keyframe)
        await self.session.flush()
        return keyframe

    async def get(self, keyframe_id: uuid.UUID) -> StoryKeyframe | None:
        """按 id 获取关键帧。"""
        return await self.session.get(StoryKeyframe, keyframe_id)

    async def get_many(
        self, keyframe_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, StoryKeyframe]:
        """批量获取关键帧，返回 {id: 关键帧}（导出快照装配防 N+1）。"""
        if not keyframe_ids:
            return {}
        stmt = select(StoryKeyframe).where(StoryKeyframe.id.in_(keyframe_ids))
        result = await self.session.execute(stmt)
        return {keyframe.id: keyframe for keyframe in result.scalars().all()}

    async def list_by_project(
        self, project_id: uuid.UUID, page: int = 1, size: int = 50
    ) -> tuple[list[StoryKeyframe], int]:
        """按项目分页列出关键帧，按章节/场景/镜头编号升序（空值靠后）。"""
        stmt = (
            select(StoryKeyframe)
            .where(StoryKeyframe.project_id == project_id)
            .order_by(
                StoryKeyframe.chapter_no.asc().nulls_last(),
                StoryKeyframe.scene_no.asc().nulls_last(),
                StoryKeyframe.shot_no.asc().nulls_last(),
                StoryKeyframe.created_at.asc(),
            )
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def exists_numbering(
        self,
        project_id: uuid.UUID,
        scene_no: int,
        shot_no: int,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        """（场景号, 镜头号）组合是否已被占用（编号均为非空时才参与判定）。"""
        stmt = select(StoryKeyframe.id).where(
            StoryKeyframe.project_id == project_id,
            StoryKeyframe.scene_no == scene_no,
            StoryKeyframe.shot_no == shot_no,
        )
        if exclude_id is not None:
            stmt = stmt.where(StoryKeyframe.id != exclude_id)
        return await self.session.scalar(stmt.limit(1)) is not None

    async def list_with_images(self, project_id: uuid.UUID) -> list[StoryKeyframe]:
        """项目下全部已带图片的关键帧（项目改名时迁移文件用）。"""
        stmt = select(StoryKeyframe).where(
            StoryKeyframe.project_id == project_id,
            StoryKeyframe.image_file.is_not(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_fields(
        self, keyframe: StoryKeyframe, fields: dict
    ) -> StoryKeyframe:
        """按传入字段局部更新并刷新 updated_at。"""
        for key, value in fields.items():
            setattr(keyframe, key, value)
        keyframe.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return keyframe

    async def delete(self, keyframe: StoryKeyframe) -> None:
        """物理删除关键帧行（出场角色由同事务内清理）。"""
        await self.session.delete(keyframe)
        await self.session.flush()


class KeyframeCharacterRepository:
    """关键帧出场角色持久层：按关键帧整体替换与按角色计数。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_for_keyframe(
        self, keyframe_id: uuid.UUID, entries: list[dict]
    ) -> list[StoryKeyframeCharacter]:
        """整体替换关键帧出场角色：先清空再按传入顺序插入（sequence 取序）。"""
        await self.delete_by_keyframe(keyframe_id)
        rows: list[StoryKeyframeCharacter] = []
        for index, entry in enumerate(entries):
            row = StoryKeyframeCharacter(
                keyframe_id=keyframe_id,
                character_id=entry["character_id"],
                character_art_id=entry.get("character_art_id"),
                role=entry.get("role"),
                character_prompt=entry.get("character_prompt"),
                sequence=index,
            )
            self.session.add(row)
            rows.append(row)
        await self.session.flush()
        return rows

    async def list_by_keyframe(
        self, keyframe_id: uuid.UUID
    ) -> list[StoryKeyframeCharacter]:
        """按出场顺序列出关键帧出场角色。"""
        stmt = (
            select(StoryKeyframeCharacter)
            .where(StoryKeyframeCharacter.keyframe_id == keyframe_id)
            .order_by(StoryKeyframeCharacter.sequence.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_keyframes(
        self, keyframe_ids: list[uuid.UUID]
    ) -> list[StoryKeyframeCharacter]:
        """批量列出多个关键帧的出场角色（按关键帧、出场顺序），防列表页 N+1。"""
        if not keyframe_ids:
            return []
        stmt = (
            select(StoryKeyframeCharacter)
            .where(StoryKeyframeCharacter.keyframe_id.in_(keyframe_ids))
            .order_by(
                StoryKeyframeCharacter.keyframe_id.asc(),
                StoryKeyframeCharacter.sequence.asc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_keyframe(self, keyframe_id: uuid.UUID) -> int:
        """物理删除关键帧下全部出场角色，返回影响行数。"""
        stmt = delete(StoryKeyframeCharacter).where(
            StoryKeyframeCharacter.keyframe_id == keyframe_id
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def clear_art_reference(self, art_id: uuid.UUID) -> int:
        """立绘删除时置空全部指向它的出场角色参考立绘引用，返回影响行数。"""
        stmt = (
            update(StoryKeyframeCharacter)
            .where(StoryKeyframeCharacter.character_art_id == art_id)
            .values(character_art_id=None)
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0


class ProjectAssetRepository:
    """项目资产编排持久层：出演登记与导出选择的增删查改。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(
        self, project_id: uuid.UUID, asset_type: str, asset_id: uuid.UUID
    ) -> bool:
        """编排行是否已存在（出演登记防重的前置检查）。"""
        stmt = select(StoryProjectAsset.id).where(
            StoryProjectAsset.project_id == project_id,
            StoryProjectAsset.asset_type == asset_type,
            StoryProjectAsset.asset_id == asset_id,
        )
        return await self.session.scalar(stmt.limit(1)) is not None

    async def add(
        self,
        asset_row_id: uuid.UUID,
        project_id: uuid.UUID,
        asset_type: str,
        asset_id: uuid.UUID,
        sort_order: int = 0,
        is_selected: bool = True,
    ) -> StoryProjectAsset:
        """插入编排行；id 由应用端生成，重复性由调用方先 exists 检查。"""
        row = StoryProjectAsset(
            id=asset_row_id,
            project_id=project_id,
            asset_type=asset_type,
            asset_id=asset_id,
            sort_order=sort_order,
            is_selected=is_selected,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def remove(
        self, project_id: uuid.UUID, asset_type: str, asset_id: uuid.UUID
    ) -> int:
        """删除编排行，返回影响行数。"""
        stmt = delete(StoryProjectAsset).where(
            StoryProjectAsset.project_id == project_id,
            StoryProjectAsset.asset_type == asset_type,
            StoryProjectAsset.asset_id == asset_id,
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def remove_by_asset(
        self, asset_type: str, asset_id: uuid.UUID
    ) -> "list[uuid.UUID]":
        """跨项目删除某资产的全部编排行（资产本体删除时清引用），返回受影响项目 id。"""
        select_stmt = select(StoryProjectAsset.project_id).where(
            StoryProjectAsset.asset_type == asset_type,
            StoryProjectAsset.asset_id == asset_id,
        )
        project_ids = [
            row[0] for row in (await self.session.execute(select_stmt)).all()
        ]
        if project_ids:
            await self.session.execute(
                delete(StoryProjectAsset).where(
                    StoryProjectAsset.asset_type == asset_type,
                    StoryProjectAsset.asset_id == asset_id,
                )
            )
        return project_ids

    async def get(
        self, project_id: uuid.UUID, asset_type: str, asset_id: uuid.UUID
    ) -> StoryProjectAsset | None:
        """获取单条编排行。"""
        stmt = select(StoryProjectAsset).where(
            StoryProjectAsset.project_id == project_id,
            StoryProjectAsset.asset_type == asset_type,
            StoryProjectAsset.asset_id == asset_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_type(
        self,
        project_id: uuid.UUID,
        asset_type: str,
        selected_only: bool = False,
    ) -> list[StoryProjectAsset]:
        """按类型列出编排行，按 sort_order 升序。"""
        stmt = select(StoryProjectAsset).where(
            StoryProjectAsset.project_id == project_id,
            StoryProjectAsset.asset_type == asset_type,
        )
        if selected_only:
            stmt = stmt.where(StoryProjectAsset.is_selected.is_(True))
        stmt = stmt.order_by(StoryProjectAsset.sort_order.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def next_sort_order(self, project_id: uuid.UUID, asset_type: str) -> int:
        """该类型编排行的下一个顺序号（当前最大 + 1，从 0 开始）。"""
        current = await self.session.scalar(
            select(func.max(StoryProjectAsset.sort_order)).where(
                StoryProjectAsset.project_id == project_id,
                StoryProjectAsset.asset_type == asset_type,
            )
        )
        return 0 if current is None else current + 1

    async def apply_sort_order(
        self, project_id: uuid.UUID, asset_type: str, ordered_ids: list[uuid.UUID]
    ) -> int:
        """按传入顺序重排编排行（逐行更新 sort_order），返回更新行数。"""
        count = 0
        for index, asset_id in enumerate(ordered_ids):
            stmt = (
                update(StoryProjectAsset)
                .where(
                    StoryProjectAsset.project_id == project_id,
                    StoryProjectAsset.asset_type == asset_type,
                    StoryProjectAsset.asset_id == asset_id,
                )
                .values(sort_order=index)
            )
            result = await self.session.execute(stmt)
            count += result.rowcount or 0
        await self.session.flush()
        return count

    async def casting_project_count(self, character_id: uuid.UUID) -> int:
        """删除守卫：角色被未删除项目出演登记的数量。"""
        stmt = (
            select(func.count())
            .select_from(StoryProjectAsset)
            .join(StoryProject, StoryProject.id == StoryProjectAsset.project_id)
            .where(
                StoryProjectAsset.asset_type == "character",
                StoryProjectAsset.asset_id == character_id,
                StoryProject.status != "deleted",
            )
        )
        return await self.session.scalar(stmt) or 0

    async def casting_projects(self, character_id: uuid.UUID) -> list[tuple]:
        """出演该角色的未删除项目（id + 标题），按出演顺序升序。"""
        stmt = (
            select(StoryProject.id, StoryProject.title)
            .select_from(StoryProjectAsset)
            .join(StoryProject, StoryProject.id == StoryProjectAsset.project_id)
            .where(
                StoryProjectAsset.asset_type == "character",
                StoryProjectAsset.asset_id == character_id,
                StoryProject.status != "deleted",
            )
            .order_by(StoryProjectAsset.sort_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.all())


class ExportPackageRepository:
    """导出包持久层：追加不可变快照，按项目/类型版本递增。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_version(self, project_id: uuid.UUID, export_type: str) -> int:
        """(project_id, export_type) 内下一个版本号（从 1 开始）。"""
        current = await self.session.scalar(
            select(func.max(StoryExportPackage.version)).where(
                StoryExportPackage.project_id == project_id,
                StoryExportPackage.export_type == export_type,
            )
        )
        return (current or 0) + 1

    async def create(
        self,
        package_id: uuid.UUID,
        project_id: uuid.UUID,
        name: str,
        payload: dict,
        prompt_text: str,
        version: int,
        export_type: str = "video_input",
        target_platform: str | None = None,
        script_id: uuid.UUID | None = None,
        copy_text: str | None = None,
        markdown_text: str | None = None,
        template_version: str | None = None,
    ) -> StoryExportPackage:
        """插入导出包快照；id 由应用端生成。"""
        package = StoryExportPackage(
            id=package_id,
            project_id=project_id,
            name=name,
            export_type=export_type,
            target_platform=target_platform,
            script_id=script_id,
            payload=payload,
            prompt_text=prompt_text,
            copy_text=copy_text,
            markdown_text=markdown_text,
            template_version=template_version,
            version=version,
        )
        self.session.add(package)
        await self.session.flush()
        return package

    async def get(self, package_id: uuid.UUID) -> StoryExportPackage | None:
        """按 id 获取导出包。"""
        return await self.session.get(StoryExportPackage, package_id)

    async def list_by_project(
        self, project_id: uuid.UUID, page: int = 1, size: int = 20
    ) -> tuple[list[StoryExportPackage], int]:
        """按项目分页列出导出包，版本倒序。"""
        stmt = (
            select(StoryExportPackage)
            .where(StoryExportPackage.project_id == project_id)
            .order_by(StoryExportPackage.version.desc())
        )
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total
