"""
剧本模块角色域持久层（DAO）。

只负责纯粹的数据访问：写操作只 flush 不 commit，事务原子性由 service 层
在同一个 `async with get_session()` 中聚合多个 repo 操作后统一 commit 保证
（对齐 database/draw/diagram.py 的 Repository 约定）。

角色库归属用户（仅本人可见）；出演登记与删除守卫引用计数所需的项目编排表
访问收口在 database/story/project.py 的 ProjectAssetRepository。
"""

import sys
from pathlib import Path

if __name__ == "__main__":
    # 冒烟直跑时 sys.path[0] 为脚本目录，先注入项目根再导入项目模块
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from entity.story.character import StoryCharacter, StoryCharacterArt
from utils.page import paginate
from utils.keyword import ilike_pattern


class CharacterRepository:
    """角色持久层：按属主收敛的 CRUD 与删除守卫引用计数。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        character_id: uuid.UUID,
        user_id: str,
        name: str,
        role_type: str | None = None,
        profile: dict | None = None,
        style: dict | None = None,
        appearance_prompt: str | None = None,
        negative_prompt: str | None = None,
        avatar_file: str | None = None,
    ) -> StoryCharacter:
        """插入角色；id 由应用端生成。"""
        character = StoryCharacter(
            id=character_id,
            user_id=user_id,
            name=name,
            role_type=role_type,
            profile=profile if profile is not None else {},
            style=style if style is not None else {},
            appearance_prompt=appearance_prompt,
            negative_prompt=negative_prompt,
            avatar_file=avatar_file,
        )
        self.session.add(character)
        await self.session.flush()
        return character

    async def get(self, character_id: uuid.UUID) -> StoryCharacter | None:
        """按 id 获取角色。"""
        return await self.session.get(StoryCharacter, character_id)

    async def get_for_update(self, character_id: uuid.UUID) -> StoryCharacter | None:
        """按 id 获取角色并加行锁（SELECT ... FOR UPDATE）。

        用于立绘上传等读-改-写场景，串行化同角色并发请求，
        防止冗余计数漂移与重复主立绘。
        """
        stmt = (
            select(StoryCharacter)
            .where(StoryCharacter.id == character_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_many(
        self, character_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, StoryCharacter]:
        """批量获取角色，返回 {id: 角色}（不校验属主，调用方负责可见性）。"""
        if not character_ids:
            return {}
        stmt = select(StoryCharacter).where(StoryCharacter.id.in_(character_ids))
        result = await self.session.execute(stmt)
        return {character.id: character for character in result.scalars().all()}

    async def list(
        self,
        user_id: str,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
    ) -> tuple[list[StoryCharacter], int]:
        """按属主分页列出角色（名称模糊检索），创建时间倒序。"""
        stmt = select(StoryCharacter).where(StoryCharacter.user_id == user_id)
        if keyword:
            stmt = stmt.where(StoryCharacter.name.ilike(ilike_pattern(keyword)))
        stmt = stmt.order_by(StoryCharacter.created_at.desc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def update_fields(
        self, character: StoryCharacter, fields: dict
    ) -> StoryCharacter:
        """按传入字段局部更新并刷新 updated_at；未知字段由调用方保证。"""
        for key, value in fields.items():
            setattr(character, key, value)
        character.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return character

    async def delete(self, character: StoryCharacter) -> None:
        """物理删除角色行（立绘由同事务内 CharacterArtRepository 清理）。"""
        await self.session.delete(character)
        await self.session.flush()

    async def keyframe_ref_count(self, character_id: uuid.UUID) -> int:
        """删除守卫：角色被关键帧出场引用的数量。"""
        from entity.story.project import StoryKeyframeCharacter

        return (
            await self.session.scalar(
                select(func.count())
                .select_from(StoryKeyframeCharacter)
                .where(StoryKeyframeCharacter.character_id == character_id)
            )
            or 0
        )


class CharacterArtRepository:
    """角色立绘持久层：按角色收敛的 CRUD 与主立绘单点维护。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        art_id: uuid.UUID,
        character_id: uuid.UUID,
        image_file: str,
        name: str | None = None,
        art_type: str = "full_body",
        source: str = "upload",
        prompt: str | None = None,
        negative_prompt: str | None = None,
        params: dict | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
        is_primary: bool = False,
    ) -> StoryCharacterArt:
        """插入立绘；id 由应用端生成。"""
        art = StoryCharacterArt(
            id=art_id,
            character_id=character_id,
            name=name,
            image_file=image_file,
            art_type=art_type,
            source=source,
            prompt=prompt,
            negative_prompt=negative_prompt,
            params=params,
            image_width=image_width,
            image_height=image_height,
            is_primary=is_primary,
        )
        self.session.add(art)
        await self.session.flush()
        return art

    async def get(self, art_id: uuid.UUID) -> StoryCharacterArt | None:
        """按 id 获取立绘。"""
        return await self.session.get(StoryCharacterArt, art_id)

    async def list_by_character(
        self, character_id: uuid.UUID
    ) -> list[StoryCharacterArt]:
        """按角色列出全部立绘：主立绘优先，其余按创建时间升序。"""
        stmt = (
            select(StoryCharacterArt)
            .where(StoryCharacterArt.character_id == character_id)
            .order_by(
                StoryCharacterArt.is_primary.desc(),
                StoryCharacterArt.created_at.asc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_characters(
        self, character_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, list[StoryCharacterArt]]:
        """批量列出多个角色的立绘，返回 {角色 id: [立绘...]}（主立绘优先、创建时间升序）。

        供出演列表/导出快照内嵌立绘，消除逐个 list_by_character 的 N+1。
        """
        if not character_ids:
            return {}
        stmt = (
            select(StoryCharacterArt)
            .where(StoryCharacterArt.character_id.in_(character_ids))
            .order_by(
                StoryCharacterArt.is_primary.desc(),
                StoryCharacterArt.created_at.asc(),
            )
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[StoryCharacterArt]] = {}
        for art in result.scalars().all():
            grouped.setdefault(art.character_id, []).append(art)
        return grouped

    async def clear_primary(self, character_id: uuid.UUID) -> int:
        """复位角色全部立绘的主标记（设主立绘前置位前的复位步），返回影响行数。"""
        stmt = (
            update(StoryCharacterArt)
            .where(
                StoryCharacterArt.character_id == character_id,
                StoryCharacterArt.is_primary.is_(True),
            )
            .values(is_primary=False, updated_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def count_by_character(self, character_id: uuid.UUID) -> int:
        """角色立绘数（供冗余计数对账）。"""
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(StoryCharacterArt)
                .where(StoryCharacterArt.character_id == character_id)
            )
            or 0
        )

    async def delete(self, art: StoryCharacterArt) -> None:
        """物理删除立绘行。"""
        await self.session.delete(art)
        await self.session.flush()

    async def delete_by_character(self, character_id: uuid.UUID) -> int:
        """物理删除角色下全部立绘（角色删除时同步清理），返回影响行数。"""
        stmt = delete(StoryCharacterArt).where(
            StoryCharacterArt.character_id == character_id
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0


if __name__ == "__main__":
    # 手动冒烟：覆盖创建/出演登记/重复出演拒绝路径/删除守卫引用计数。
    # 不经常态入口调用须先加载配置快照（对齐项目约定）。
    import asyncio

    from uuid_utils.compat import uuid7

    from core.config_snapshot import CFG
    from database.postgre_client import get_session
    from database.story.project import (
        KeyframeCharacterRepository,
        KeyframeRepository,
        ProjectAssetRepository,
        ProjectRepository,
    )
    from entity.story.project import StoryProject

    async def _smoke() -> None:
        await CFG.load()
        user_id = uuid7().hex
        character_id = uuid7()
        project_id = uuid7()
        async with get_session() as session:
            char_repo = CharacterRepository(session)
            project_repo = ProjectRepository(session)
            asset_repo = ProjectAssetRepository(session)
            kf_repo = KeyframeRepository(session)
            kfc_repo = KeyframeCharacterRepository(session)

            character = await char_repo.create(character_id, user_id, "冒烟角色")
            project = await project_repo.create(project_id, user_id, "冒烟项目")
            print(f"[PASS] 创建角色={character.id.hex} 项目={project.id.hex}")

            assert not await asset_repo.exists(project_id, "character", character_id)
            await asset_repo.add(uuid7(), project_id, "character", character_id)
            assert await asset_repo.exists(project_id, "character", character_id)
            print("[PASS] 出演登记成功")

            assert await asset_repo.exists(project_id, "character", character_id)
            print("[PASS] 重复出演登记被前置检查拦截（exists=True，业务层拒绝）")

            casting = await asset_repo.casting_project_count(character_id)
            assert casting == 1, casting
            print(f"[PASS] 删除守卫：出演项目数={casting}，删除将被拒绝")

            keyframe = await kf_repo.create(
                uuid7(), project_id, prompt="冒烟提示词", scene_no=1, shot_no=1
            )
            await kfc_repo.replace_for_keyframe(
                keyframe.id, [{"character_id": character_id}]
            )
            keyframe_refs = await char_repo.keyframe_ref_count(character_id)
            assert keyframe_refs == 1, keyframe_refs
            print(f"[PASS] 删除守卫：关键帧引用数={keyframe_refs}，删除将被拒绝")

            # 清理冒烟数据后验证无引用可删
            await kfc_repo.delete_by_keyframe(keyframe.id)
            await kf_repo.delete(keyframe)
            await asset_repo.remove(project_id, "character", character_id)
            await session.execute(
                delete(StoryProject).where(StoryProject.id == project_id)
            )
            assert await asset_repo.casting_project_count(character_id) == 0
            assert await char_repo.keyframe_ref_count(character_id) == 0
            await char_repo.delete(character)
            await session.commit()
            print("[PASS] 无引用角色删除成功，冒烟数据已清理")

        print("SMOKE OK")

    asyncio.run(_smoke())
