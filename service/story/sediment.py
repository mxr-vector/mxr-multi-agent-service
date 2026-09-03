"""
剧本模块沉淀业务层：生成会话产物 → 正式资产（story-ai-workspace）。

三类沉淀动作，均以会话消息为输入：
- 剧本卡"存为版本"：kind='script' 消息 → story_scripts 新版本
  （source='ai'，source_message_id/generation_task_id 溯源；重复沉淀产生
  新版本而非覆盖，对齐 spec）；
- 角色卡编辑：kind='character' 消息上的卡片字段修订（沉淀以修订后内容
  入库，对齐 spec"编辑后沉淀以修订内容入库"场景）；
- 角色卡"存入角色库"：单事务完成 建角色 → 立绘（source='ai'，会话内
  已生成的 art 消息一并收编）→ 出演登记 → 冗余计数重算；同名角色由
  前端先行提示，服务端按 mode（new/merge）执行；卡片与立绘消息打上
  sedimented 标记保证幂等（重复沉淀拒绝）。

未沉淀的产物不进任何正式资产表，随会话删除丢弃。
"""

import uuid

from sqlalchemy import select
from uuid_utils.compat import uuid7

from agent.constants.enums.chat import ChatMessageStatus
from agent.constants.enums.story import StoryMessageKind
from agent.prompts.story import CARD_DATA_KEY
from database.postgre_client import get_session
from database.story.character import CharacterArtRepository, CharacterRepository
from database.story.project import (
    ProjectAssetRepository,
    ProjectRepository,
    ScriptRepository,
)
from database.story.session import MessageRepository
from entity.story.session import StoryMessage
from exception.bad_except import bad_except
from model.image.factory import OUTPUT_FORMAT
from service.story.storage import (
    character_art_dir,
    resolve_upload_path,
    unlink_quietly,
    write_seq_file,
)

# 消息沉淀标记键（幂等守卫）
_SEDIMESTED_KEY = "sedimented_character_id"

# 角色名长度上限（对齐 service/story/character.py 的 _CHARACTER_NAME_MAX，
# 沉淀路径绕过 CharacterService 校验，需在此拦住超长 AI 产出）
_NAME_MAX = 100

# 卡片可编辑字段白名单
_CARD_EDITABLE = {
    "name",
    "role_type",
    "profile",
    "visual_profile",
    "appearance_prompt",
    "art_prompt",
    "negative_prompt",
}


class SedimentService:
    """沉淀业务层：剧本版本 / 角色库角色两条收敛路径。"""

    # ---------- 共享 ----------

    async def _assert_message_owned(self, db, message_id: uuid.UUID, ctx):
        """消息须存在且所属项目归属当前用户，返回 (消息, 项目)。"""
        from service.story.art import ArtGenerationService

        message, story_session, project = await ArtGenerationService()._assert_message_owned(
            db, message_id, ctx
        )
        return message, project

    def _load_card(self, message: StoryMessage) -> dict:
        """取角色卡数据（缺失/非卡片消息拒绝）。"""
        card = (message.params or {}).get(CARD_DATA_KEY)
        if message.kind != StoryMessageKind.CHARACTER.value or not isinstance(card, dict):
            bad_except("该消息不是角色卡")
        return card

    # ---------- 角色卡编辑（沉淀前修订） ----------

    async def edit_card(self, ctx, message_id: uuid.UUID, fields: dict) -> dict:
        """编辑角色卡字段（白名单内显式传入）；修订直接更新消息卡片数据。"""
        if not ctx.user_id:
            bad_except("角色卡仅支持用户通道调用")
        updates = {
            key: value for key, value in (fields or {}).items() if key in _CARD_EDITABLE
        }
        if not updates:
            bad_except("没有可编辑的字段")
        async with get_session() as db:
            message, _ = await self._assert_message_owned(db, message_id, ctx)
            card = dict(self._load_card(message))
            if "name" in updates:
                name = str(updates["name"] or "").strip()
                if not name:
                    bad_except("角色名不能为空")
                if len(name) > _NAME_MAX:
                    bad_except(f"角色名不能超过 {_NAME_MAX} 字符")
                updates["name"] = name
            if "role_type" in updates and updates["role_type"] not in (
                None,
                "protagonist",
                "supporting",
                "antagonist",
                "npc",
                "other",
            ):
                bad_except(f"角色类型非法: {updates['role_type']}")
            card.update(updates)
            message.params = {
                **(message.params or {}),
                CARD_DATA_KEY: card,
                "edited_by_user": True,
            }
            message.content = f"角色卡：{card['name']}"
            await MessageRepository(db).update_fields(message, {})
            await db.commit()
            return message.to_dict()

    # ---------- 剧本沉淀 ----------

    async def save_script(self, ctx, message_id: uuid.UUID, title: str | None, set_current: bool) -> dict:
        """剧本卡"存为版本"：kind='script' 消息 → 项目剧本新版本（source='ai'）。"""
        if not ctx.user_id:
            bad_except("剧本沉淀仅支持用户通道调用")
        async with get_session() as db:
            message, project = await self._assert_message_owned(db, message_id, ctx)
            if message.kind != StoryMessageKind.SCRIPT.value:
                bad_except("该消息不是剧本卡")
            if message.status != ChatMessageStatus.DONE.value or not (message.content or "").strip():
                bad_except("该剧本卡尚未完成，无法沉淀")
            # 行锁串行化版本号分配（对齐 ScriptService.save）
            project_repo = ProjectRepository(db)
            await project_repo.get_for_update(project.id)
            script_repo = ScriptRepository(db)
            version = await script_repo.next_version(project.id)
            current = await script_repo.get_current(project.id)
            make_current = set_current or current is None
            if make_current:
                await script_repo.clear_current(project.id)
            script = await script_repo.create(
                script_id=uuid7(),
                project_id=project.id,
                version=version,
                content=message.content.strip(),
                title=(title or "").strip() or None,
                source="ai",
                source_message_id=message.id,
                generation_task_id=self._gen_task_id(message),
                is_current=make_current,
            )
            await project_repo.recount_assets(project)
            await db.commit()
            return script.to_dict()

    @staticmethod
    def _gen_task_id(message: StoryMessage) -> uuid.UUID | None:
        """从消息 params 提取生成任务 id（溯源用，缺失返回 None）。"""
        raw = (message.params or {}).get("generation_task_id")
        if not raw:
            return None
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None

    # ---------- 角色卡沉淀 ----------

    async def save_character(
        self,
        ctx,
        message_id: uuid.UUID,
        mode: str,
        character_id: uuid.UUID | None,
    ) -> dict:
        """角色卡"存入角色库"：单事务完成建角色/并入 + 立绘收编 + 出演登记。

        mode='new' 新建角色（同名由前端先行提示选择）；mode='merge' 并入
        character_id 指向的既有角色（仅新增立绘与出演登记，不改人设）。
        """
        if not ctx.user_id:
            bad_except("角色沉淀仅支持用户通道调用")
        if mode not in ("new", "merge"):
            bad_except(f"沉淀方式非法: {mode}")
        if mode == "merge" and character_id is None:
            bad_except("并入既有角色时须提供 character_id")
        async with get_session() as db:
            _, project = await self._assert_message_owned(db, message_id, ctx)
            # 行锁串行化幂等检查：并发双击/重试时先加锁再读标记，防
            # "读-改-写"窗口内两个请求同时通过检查各自建角色（重复沉淀）
            message = await MessageRepository(db).get_for_update(message_id)
            if message is None:
                bad_except(f"消息不存在: {message_id.hex}")
            card = self._load_card(message)
            if (message.params or {}).get(_SEDIMESTED_KEY):
                bad_except("该角色卡已沉淀过，请勿重复操作")
            name = str(card.get("name") or "").strip()
            if not name:
                bad_except("角色卡缺少角色名，请先编辑补全")
            if len(name) > _NAME_MAX:
                bad_except(f"角色名不能超过 {_NAME_MAX} 字符")

            char_repo = CharacterRepository(db)
            art_repo = CharacterArtRepository(db)
            asset_repo = ProjectAssetRepository(db)

            if mode == "new":
                character = await char_repo.create(
                    character_id=uuid7(),
                    user_id=ctx.user_id,
                    name=name,
                    role_type=card.get("role_type"),
                    profile=card.get("profile") or {},
                    style=card.get("visual_profile") or {},
                    appearance_prompt=card.get("appearance_prompt"),
                    negative_prompt=card.get("negative_prompt"),
                )
            else:
                character = await char_repo.get_for_update(character_id)
                if character is None or character.user_id != ctx.user_id:
                    bad_except("角色不存在")

            # 收编会话内已生成且未沉淀的立绘消息（复制文件进角色目录）；
            # 复制件登记 copied_files，事务失败回滚时补偿回收（对齐
            # service/story/project.py 的 _rollback_keyframe_moves 范式，
            # 避免留下无 DB 引用的孤儿文件）
            art_messages = await self._collect_art_messages(db, message_id)
            made_primary = not any(
                art.is_primary for art in await art_repo.list_by_character(character.id)
            )
            saved_arts = []
            copied_files: "list[str]" = []
            try:
                for index, art_message in enumerate(art_messages):
                    image_file = await self._copy_into_character_dir(
                        art_message.image_file, ctx.user_id, character
                    )
                    copied_files.append(image_file)
                    art = await art_repo.create(
                        art_id=uuid7(),
                        character_id=character.id,
                        image_file=image_file,
                        name=character.name,
                        art_type="full_body",
                        source="ai",
                        prompt=art_message.prompt,
                        negative_prompt=card.get("negative_prompt"),
                        params={
                            "source_message_id": art_message.id.hex,
                            "generation_task_id": (art_message.params or {}).get(
                                "generation_task_id"
                            ),
                        },
                        is_primary=made_primary and index == 0,
                    )
                    saved_arts.append(art)
                    # 沉淀标记（幂等守卫）
                    art_message.params = {
                        **(art_message.params or {}),
                        _SEDIMESTED_KEY: character.id.hex,
                    }
                    await MessageRepository(db).update_fields(art_message, {})

                # 冗余计数按真实数量重算；merge 模式不改共享角色的头像
                # （头像跨项目可见，本入口无"改全局角色"预期，防可见漂移）
                character.art_count = len(await art_repo.list_by_character(character.id))
                if mode == "new" and saved_arts and not character.avatar_file:
                    character.avatar_file = saved_arts[0].image_file

                # 出演登记（引用既有编排语义，重复登记静默跳过）
                casting_added = False
                if not await asset_repo.exists(project.id, "character", character.id):
                    sort_order = await asset_repo.next_sort_order(project.id, "character")
                    await asset_repo.add(
                        uuid7(), project.id, "character", character.id, sort_order=sort_order
                    )
                    casting_added = True

                # 项目冗余计数重算（character_count/art_count 口径为编排表）
                await ProjectRepository(db).recount_assets(project)

                # 卡片消息沉淀标记
                message.params = {
                    **(message.params or {}),
                    _SEDIMESTED_KEY: character.id.hex,
                }
                await MessageRepository(db).update_fields(message, {})
                await db.commit()
            except BaseException:
                # 事务已回滚，回收已落盘的复制件（尽力而为，不掩盖原异常）
                for rel in copied_files:
                    unlink_quietly(rel)
                raise
            return {
                "mode": mode,
                "character": character.to_dict(),
                "saved_art_count": len(saved_arts),
                "casting_added": casting_added,
            }

    async def _collect_art_messages(
        self, db, card_message_id: uuid.UUID
    ) -> list[StoryMessage]:
        """会话内归属本卡片、已完成且未沉淀的 art 消息（创建顺序）。"""
        stmt = (
            select(StoryMessage)
            .where(
                StoryMessage.kind == StoryMessageKind.ART.value,
                StoryMessage.status == ChatMessageStatus.DONE.value,
                StoryMessage.params["card_message_id"].astext == card_message_id.hex,
            )
            .order_by(StoryMessage.created_at.asc())
        )
        rows = list((await db.execute(stmt)).scalars().all())
        return [
            row
            for row in rows
            if row.image_file and not (row.params or {}).get(_SEDIMESTED_KEY)
        ]

    async def _copy_into_character_dir(
        self, source_relative: str, user_id: str, character
    ) -> str:
        """把会话立绘文件复制进角色目录（保留会话原件，命名与上传规则一致）。"""
        import asyncio

        src = resolve_upload_path(source_relative)
        if not src.is_file():
            bad_except(f"立绘文件缺失: {source_relative}")
        rel_dir = character_art_dir(user_id, character.name, character.id.hex)
        content = await asyncio.to_thread(src.read_bytes)
        # 扩展名随源文件（生成侧统一 OUTPUT_FORMAT，防双头定义漂移后缀与字节不符）
        ext = src.suffix.lstrip(".") or OUTPUT_FORMAT
        # 文件名前缀为角色名（对齐立绘存储约定 <角色名>_<序号>.<ext>，O_EXCL 原子）
        filename = await asyncio.to_thread(
            write_seq_file, resolve_upload_path(rel_dir), character.name, ext, content
        )
        return f"{rel_dir}/{filename}"
