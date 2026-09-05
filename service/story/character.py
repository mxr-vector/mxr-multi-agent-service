"""
剧本模块角色库业务层：用户级角色/立绘维护与项目出演登记。

- 角色归属当前登录用户，仅本人可见；非属主访问一律按"角色不存在"
  业务失败（与知识库可见性约定一致，不暴露资源存在性）；
- 立绘随角色归属用户；主立绘单点（切换时先复位再置位），角色头像跟随主立绘；
- 立绘文件存放在 UPLOAD_DIR 下以角色名命名的目录中，角色改名时迁移；
- 出演登记为编排表引用（非拷贝），防重、可排序；
- 角色删除守卫：被未删除项目出演或被关键帧引用时拒绝删除。
"""

import asyncio
import uuid
from datetime import datetime, timezone

from uuid_utils.compat import uuid7

from agent.constants.enums.story import StoryProjectStatus
from database.postgre_client import get_session
from database.story.character import CharacterArtRepository, CharacterRepository
from database.story.project import (
    KeyframeCharacterRepository,
    ProjectAssetRepository,
    ProjectRepository,
)
from exception.bad_except import bad_except
from service.story.storage import (
    art_filename_seq,
    assert_asset_relative,
    character_art_dir,
    move_without_overwrite,
    rmdir_if_empty,
    resolve_upload_path,
    sanitize_dir_name,
    unlink_quietly,
    used_art_seqs,
    write_seq_file,
)
from utils.env import ENV
from utils.id import format_id
from utils.logger import logger

# 角色可更新字段白名单（防越权覆盖属主/冗余计数字段）
_CHARACTER_UPDATABLE = {
    "name",
    "role_type",
    "profile",
    "style",
    "appearance_prompt",
    "negative_prompt",
    "avatar_file",
}

# 长度上限（对齐 schema VARCHAR 定义，服务端强校验防溢出 500）
_CHARACTER_NAME_MAX = 100
_ART_NAME_MAX = 100

# 立绘类型白名单：三视图与正面半身特写为外部视频生成的必备参考图
ART_TYPES = {
    "turnaround",  # 三视图
    "front_bust",  # 正面半身特写
    "full_body",
    "half_body",
    "face",
    "action",
    "reference",
    "other",
}

# 必备参考图类型（角色详情页完整性提示用）
REQUIRED_ART_TYPES = ("turnaround", "front_bust")


def _assert_user_channel(ctx) -> None:
    """角色库仅支持用户通道调用（机器通道无属主概念）。"""
    if not ctx.user_id:
        bad_except("角色库仅支持用户通道调用")


class CharacterService:
    """角色与立绘业务层：属主校验收口 + 删除守卫。"""

    async def _assert_owned(
        self, repo: CharacterRepository, character_id: uuid.UUID, ctx
    ):
        """角色须存在且归属当前用户，否则按不存在处理。"""
        character = await repo.get(character_id)
        if character is None or character.user_id != ctx.user_id:
            bad_except("角色不存在")
        return character

    async def list(self, ctx, page: int, size: int, keyword: str | None = None):
        """分页列出本人角色库，创建时间倒序。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            items, total = await CharacterRepository(session).list(
                ctx.user_id, page, size, keyword
            )
            return [item.to_dict() for item in items], total

    async def detail(self, ctx, character_id: uuid.UUID) -> dict:
        """角色详情：本体 + 全部立绘 + 出演项目提示。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            repo = CharacterRepository(session)
            character = await self._assert_owned(repo, character_id, ctx)
            arts = await CharacterArtRepository(session).list_by_character(character_id)
            castings = await ProjectAssetRepository(session).casting_projects(
                character_id
            )
            data = character.to_dict()
            data["arts"] = [art.to_dict() for art in arts]
            data["casting_projects"] = [
                {"project_id": format_id(project_id), "title": title}
                for project_id, title in castings
            ]
            return data

    async def create(self, ctx, payload) -> dict:
        """创建角色（名称必填）。"""
        _assert_user_channel(ctx)
        name = (payload.name or "").strip()
        if not name:
            bad_except("角色名不能为空")
        if len(name) > _CHARACTER_NAME_MAX:
            bad_except(f"角色名不能超过 {_CHARACTER_NAME_MAX} 字符")
        assert_asset_relative(payload.avatar_file, ("story/characters/",))
        async with get_session() as session:
            character = await CharacterRepository(session).create(
                character_id=uuid7(),
                user_id=ctx.user_id,
                name=name,
                role_type=payload.role_type,
                profile=payload.profile or {},
                style=payload.style or {},
                appearance_prompt=payload.appearance_prompt,
                negative_prompt=payload.negative_prompt,
                avatar_file=payload.avatar_file,
            )
            await session.commit()
            return character.to_dict()

    async def update(self, ctx, character_id: uuid.UUID, payload) -> dict:
        """局部更新角色字段（仅白名单字段，显式传入才更新）。"""
        _assert_user_channel(ctx)
        fields = {
            key: value
            for key, value in payload.model_dump(exclude_unset=True).items()
            if key in _CHARACTER_UPDATABLE
        }
        if not fields:
            bad_except("没有可更新的字段")
        if "name" in fields:
            fields["name"] = (fields["name"] or "").strip()
            if not fields["name"]:
                bad_except("角色名不能为空")
            if len(fields["name"]) > _CHARACTER_NAME_MAX:
                bad_except(f"角色名不能超过 {_CHARACTER_NAME_MAX} 字符")
        if "avatar_file" in fields:
            assert_asset_relative(fields["avatar_file"], ("story/characters/",))
        async with get_session() as session:
            repo = CharacterRepository(session)
            # 行锁串行化同角色并发改名/上传：与 add_art 一致，防序号交错后 move 覆盖立绘
            character = await repo.get_for_update(character_id)
            if character is None or character.user_id != ctx.user_id:
                bad_except("角色不存在")
            old_name = character.name
            await repo.update_fields(character, fields)
            if "name" in fields and fields["name"] != old_name:
                await self._relocate_art_files(session, character, old_name)
            await session.commit()
            return character.to_dict()

    async def _relocate_art_files(self, session, character, old_name: str) -> None:
        """改名后将立绘文件迁移至新角色名目录并以新名前缀重命名，同步 DB 路径与头像。

        复用调用方会话（随 update 一并提交）；文件缺失/迁移失败不阻断改名，
        保留原路径并记录告警。文件名沿用 <新角色名>_<原序号>（原名无法解析
        序号时分配未占用序号），序号冲突顺延。
        """
        art_repo = CharacterArtRepository(session)
        arts = await art_repo.list_by_character(character.id)
        if not arts:
            return
        new_dir = character_art_dir(character.user_id, character.name, character.id.hex)
        old_dir = character_art_dir(character.user_id, old_name, character.id.hex)
        if new_dir == old_dir:
            return
        new_dir_name = sanitize_dir_name(character.name, character.id.hex)
        old_dir_name = sanitize_dir_name(old_name, character.id.hex)
        base = ENV.upload_dir

        def _move_all() -> dict[str, str]:
            moved: dict[str, str] = {}
            src_parents: set[str] = set()
            target_dir = base / new_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            used = used_art_seqs(target_dir, new_dir_name)
            for art in arts:
                try:
                    src = resolve_upload_path(art.image_file)
                except Exception:
                    logger.warning(f"[STORY] 立绘路径非法，跳过迁移: {art.image_file}")
                    continue
                if not src.is_file():
                    logger.warning(f"[STORY] 立绘文件缺失，跳过迁移: {art.image_file}")
                    continue
                seq = art_filename_seq(src.name, old_dir_name)
                if seq is None:
                    seq = (max(used) + 1) if used else 1
                while seq in used:
                    seq += 1
                used.add(seq)
                new_rel = f"{new_dir}/{new_dir_name}_{seq}{src.suffix}"
                try:
                    # 不覆盖语义：目标已存在（并发上传占用）即跳过，杜绝覆盖刚落盘文件
                    move_without_overwrite(src, base / new_rel)
                except FileExistsError:
                    logger.warning(f"[STORY] 立绘迁移目标已存在，跳过不覆盖: {new_rel}")
                    continue
                except OSError as exc:
                    logger.warning(f"[STORY] 立绘文件迁移失败: {art.image_file}: {exc}")
                    continue
                moved[art.image_file] = new_rel
                idx = art.image_file.rfind("/")
                if idx > 0:
                    src_parents.add(art.image_file[:idx])
            # 迁移后按实际源目录尽力清理空目录（兼容历史非命名空间布局）
            for parent in src_parents:
                try:
                    src_dir = base / parent
                    if src_dir.is_dir() and not any(src_dir.iterdir()):
                        src_dir.rmdir()
                except OSError:
                    pass
            return moved

        moved = await asyncio.to_thread(_move_all)
        if not moved:
            return
        for art in arts:
            new_rel = moved.get(art.image_file)
            if new_rel:
                art.image_file = new_rel
                art.updated_at = datetime.now(timezone.utc)
        if character.avatar_file in moved:
            character.avatar_file = moved[character.avatar_file]
        await session.flush()

    async def delete(self, ctx, character_id: uuid.UUID) -> None:
        """删除角色：出演/关键帧引用守卫，通过后同事务清理立绘。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            repo = CharacterRepository(session)
            character = await self._assert_owned(repo, character_id, ctx)
            casting_count = await ProjectAssetRepository(session).casting_project_count(
                character_id
            )
            if casting_count > 0:
                bad_except(f"角色正被 {casting_count} 个项目出演，请先移除出演登记")
            keyframe_refs = await repo.keyframe_ref_count(character_id)
            if keyframe_refs > 0:
                bad_except(f"角色被 {keyframe_refs} 个关键帧引用，请先解除引用")
            art_repo = CharacterArtRepository(session)
            image_files = [
                art.image_file for art in await art_repo.list_by_character(character_id)
            ]
            await art_repo.delete_by_character(character_id)
            await repo.delete(character)
            await session.commit()

        # 提交成功后按 DB 记录精确清理文件（不整目录 rmtree，防误删同名角色/他人文件）
        def _cleanup() -> None:
            parents: set[str] = set()
            for relative in image_files:
                unlink_quietly(relative)
                idx = relative.rfind("/")
                if idx > 0:
                    parents.add(relative[:idx])
            # 按实际源目录清理空目录（兼容历史非命名空间布局）
            for parent in parents:
                rmdir_if_empty(parent)

        await asyncio.to_thread(_cleanup)

    async def add_art(
        self,
        ctx,
        character_id: uuid.UUID,
        file_data: bytes,
        ext: str,
        name: str | None = None,
        art_type: str = "full_body",
    ) -> dict:
        """上传立绘：文件以 角色名_序号 原子命名存入角色名目录；首张自动设为主立绘并同步头像。"""
        _assert_user_channel(ctx)
        if art_type not in ART_TYPES:
            bad_except(f"立绘类型非法: {art_type}")
        if name and len(name) > _ART_NAME_MAX:
            bad_except(f"立绘名不能超过 {_ART_NAME_MAX} 字符")
        async with get_session() as session:
            repo = CharacterRepository(session)
            # 行锁串行化同角色并发上传：防重复主立绘与计数漂移
            character = await repo.get_for_update(character_id)
            if character is None or character.user_id != ctx.user_id:
                bad_except("角色不存在")
            art_dir = character_art_dir(
                character.user_id, character.name, character.id.hex
            )
            dir_name = sanitize_dir_name(character.name, character.id.hex)
            target_dir = ENV.upload_dir / art_dir

            # O_EXCL 原子创建，序号冲突自动顺延（并发/同名角色共享目录不互相覆盖）
            def _save() -> str:
                filename = write_seq_file(target_dir, dir_name, ext, file_data)
                return f"{art_dir}/{filename}"

            relative = await asyncio.to_thread(_save)

            art_repo = CharacterArtRepository(session)
            db_count = await art_repo.count_by_character(character_id)
            is_first = db_count == 0
            art = await art_repo.create(
                art_id=uuid7(),
                character_id=character_id,
                image_file=relative,
                name=name,
                art_type=art_type,
                is_primary=is_first,
            )
            count_fields: dict = {"art_count": db_count + 1}
            if is_first:
                count_fields["avatar_file"] = relative
            await repo.update_fields(character, count_fields)
            await session.commit()
            return art.to_dict()

    async def set_primary_art(
        self, ctx, character_id: uuid.UUID, art_id: uuid.UUID
    ) -> dict:
        """设主立绘：先复位该角色全部主标记再置位，头像同步为立绘图。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            repo = CharacterRepository(session)
            character = await self._assert_owned(repo, character_id, ctx)
            art_repo = CharacterArtRepository(session)
            art = await art_repo.get(art_id)
            if art is None or art.character_id != character_id:
                bad_except("立绘不存在")
            await art_repo.clear_primary(character_id)
            art.is_primary = True
            await session.flush()
            await repo.update_fields(character, {"avatar_file": art.image_file})
            await session.commit()
            return art.to_dict()

    async def delete_art(self, ctx, character_id: uuid.UUID, art_id: uuid.UUID) -> None:
        """删除立绘：同步清理引用（各项目立绘选择行、关键帧参考立绘置空）并重算受影响项目；
        删除主立绘时提升最早一张继任；清空时复位头像；物理文件精确清理。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            repo = CharacterRepository(session)
            character = await self._assert_owned(repo, character_id, ctx)
            art_repo = CharacterArtRepository(session)
            art = await art_repo.get(art_id)
            if art is None or art.character_id != character_id:
                bad_except("立绘不存在")
            was_primary = art.is_primary
            image_file = art.image_file
            # 引用清理：跨项目编排选择行 + 关键帧出场角色的参考立绘引用
            asset_repo = ProjectAssetRepository(session)
            affected_project_ids = await asset_repo.remove_by_asset(
                "character_art", art_id
            )
            await KeyframeCharacterRepository(session).clear_art_reference(art_id)
            await art_repo.delete(art)
            db_count = await art_repo.count_by_character(character_id)
            fields: dict = {"art_count": db_count}
            if was_primary:
                remaining = await art_repo.list_by_character(character_id)
                if remaining:
                    successor = remaining[0]
                    successor.is_primary = True
                    await session.flush()
                    fields["avatar_file"] = successor.image_file
                else:
                    fields["avatar_file"] = None
            await repo.update_fields(character, fields)
            project_repo = ProjectRepository(session)
            for pid in affected_project_ids:
                project = await project_repo.get(pid)
                if project is not None:
                    await project_repo.recount_assets(project)
            await session.commit()

        # 提交成功后精确清理立绘文件与空目录（失败仅告警）
        def _cleanup() -> None:
            unlink_quietly(image_file)
            parent = image_file.rsplit("/", 1)[0] if "/" in image_file else None
            if parent:
                rmdir_if_empty(parent)

        await asyncio.to_thread(_cleanup)


class CastingService:
    """项目出演登记业务层：编排表引用角色库角色，防重、可排序。"""

    async def _assert_project(self, session, project_id: uuid.UUID, ctx):
        """项目须存在、未删除且归属当前用户。"""
        project = await ProjectRepository(session).get(project_id)
        if (
            project is None
            or project.status == StoryProjectStatus.DELETED
            or project.user_id != ctx.user_id
        ):
            bad_except("项目不存在")
        return project

    async def _assert_character(self, session, character_id: uuid.UUID, ctx):
        """角色须存在且归属当前用户（跨用户引用按不存在处理）。"""
        character = await CharacterRepository(session).get(character_id)
        if character is None or character.user_id != ctx.user_id:
            bad_except("角色不存在")
        return character

    async def list(self, ctx, project_id: uuid.UUID) -> "list[dict]":
        """项目出演角色列表（含角色完整信息、全部立绘与选中立绘），按出演顺序升序。

        批量加载角色与立绘（各一次 IN 查询）并内嵌 arts，供前端直接渲染，
        免去前端逐个 detail 的 N+1 HTTP 放大。
        """
        _assert_user_channel(ctx)
        async with get_session() as session:
            await self._assert_project(session, project_id, ctx)
            asset_repo = ProjectAssetRepository(session)
            rows = await asset_repo.list_by_type(project_id, "character")
            char_ids = {row.asset_id for row in rows}
            # 批量加载角色本体与全部立绘（内嵌，免前端逐个 detail）
            characters = await CharacterRepository(session).get_many(char_ids)
            arts_by_char = await CharacterArtRepository(session).list_by_characters(
                char_ids
            )
            # 选中立绘按角色聚合（供前端预选），保持编排 sort_order 次序
            art_to_char = {
                art.id: char_id
                for char_id, arts in arts_by_char.items()
                for art in arts
            }
            selected_by_character: dict[uuid.UUID, list[str]] = {}
            for art_row in await asset_repo.list_by_type(project_id, "character_art"):
                char_id = art_to_char.get(art_row.asset_id)
                if char_id is not None:
                    selected_by_character.setdefault(char_id, []).append(
                        format_id(art_row.asset_id)
                    )
            items = []
            for row in rows:
                character = characters.get(row.asset_id)
                if character is None:
                    continue  # 脏数据容错：角色已不存在则跳过
                data = character.to_dict()
                data["sort_order"] = row.sort_order
                data["selected_art_ids"] = selected_by_character.get(row.asset_id, [])
                data["arts"] = [
                    art.to_dict() for art in arts_by_char.get(row.asset_id, [])
                ]
                items.append(data)
            return items

    async def add(self, ctx, project_id: uuid.UUID, character_id: uuid.UUID) -> dict:
        """出演登记：重复登记拒绝；成功后重算项目冗余计数。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            project = await self._assert_project(session, project_id, ctx)
            character = await self._assert_character(session, character_id, ctx)
            asset_repo = ProjectAssetRepository(session)
            if await asset_repo.exists(project_id, "character", character_id):
                bad_except("该角色已在本项目出演")
            sort_order = await asset_repo.next_sort_order(project_id, "character")
            await asset_repo.add(
                uuid7(), project_id, "character", character_id, sort_order=sort_order
            )
            await ProjectRepository(session).recount_assets(project)
            await session.commit()
            return character.to_dict()

    async def remove(self, ctx, project_id: uuid.UUID, character_id: uuid.UUID) -> None:
        """移除出演登记；未出演时业务失败；同步清理该角色的立绘选择行，重算项目计数。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            project = await self._assert_project(session, project_id, ctx)
            asset_repo = ProjectAssetRepository(session)
            removed = await asset_repo.remove(project_id, "character", character_id)
            if removed == 0:
                bad_except("该角色未在本项目出演")
            # 同步移除该角色在本项目的立绘选择，避免孤儿编排行与 art_count 虚高
            for art in await CharacterArtRepository(session).list_by_character(
                character_id
            ):
                await asset_repo.remove(project_id, "character_art", art.id)
            await ProjectRepository(session).recount_assets(project)
            await session.commit()

    async def sort(
        self, ctx, project_id: uuid.UUID, character_ids: "list[uuid.UUID]"
    ) -> None:
        """重排出演顺序：传入集合须与项目当前出演集合完全一致。"""
        _assert_user_channel(ctx)
        async with get_session() as session:
            await self._assert_project(session, project_id, ctx)
            asset_repo = ProjectAssetRepository(session)
            current = await asset_repo.list_by_type(project_id, "character")
            current_ids = {row.asset_id for row in current}
            if set(character_ids) != current_ids or len(character_ids) != len(
                current_ids
            ):
                bad_except("出演角色列表与项目实际不符")
            await asset_repo.apply_sort_order(project_id, "character", character_ids)
            await session.commit()

    async def set_art_selection(
        self, ctx, project_id: uuid.UUID, art_ids: "list[uuid.UUID]"
    ) -> "list[dict]":
        """整体设置项目选中立绘（编排表替换），空列表清空选择。

        立绘必须归属本项目出演角色；按传入顺序记录顺序。
        """
        _assert_user_channel(ctx)
        # 入参保序去重：防重复 id 触发 UNIQUE(project_id, asset_type, asset_id) 返回 500
        art_ids = list(dict.fromkeys(art_ids))
        async with get_session() as session:
            project = await self._assert_project(session, project_id, ctx)
            asset_repo = ProjectAssetRepository(session)
            cast_ids = {
                row.asset_id
                for row in await asset_repo.list_by_type(project_id, "character")
            }
            art_repo = CharacterArtRepository(session)
            for art_id in art_ids:
                art = await art_repo.get(art_id)
                if art is None or art.character_id not in cast_ids:
                    bad_except("立绘不存在或不属于本项目出演角色")
            for row in await asset_repo.list_by_type(project_id, "character_art"):
                await asset_repo.remove(project_id, "character_art", row.asset_id)
            for index, art_id in enumerate(art_ids):
                await asset_repo.add(
                    uuid7(), project_id, "character_art", art_id, sort_order=index
                )
            await ProjectRepository(session).recount_assets(project)
            rows = await asset_repo.list_by_type(project_id, "character_art")
            await session.commit()
            return [row.to_dict() for row in rows]
