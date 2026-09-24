"""
剧本模块关键帧业务层：五段式描述维护、编号冲突校验与出场角色登记。

- (场景号, 镜头号) 组合项目内唯一（编号均为非空时参与判定）；
- 出场角色按关键帧整体替换（含参考立绘与镜头内局部描述）；
- 关键帧可附带一张图片，按 项目名/关键帧名 目录存储，改名时迁移；
- 删除关键帧同步清理出场角色与导出编排引用，并重算项目计数。
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from uuid_utils.compat import uuid7
from sqlalchemy import select

from agent.constants.enums.story import (
    StoryKeyframeStatus,
    StoryTaskStatus,
    StoryTaskType,
)
from core.config_snapshot import CFG
from database.postgre_client import get_session
from entity.story.session import StoryGenerationTask
from database.story.character import CharacterArtRepository, CharacterRepository
from database.story.project import (
    KeyframeCharacterRepository,
    KeyframeRepository,
    ProjectAssetRepository,
    ProjectRepository,
    ScriptRepository,
)
from database.story.session import GenerationTaskRepository
from exception.bad_except import bad_except
from model.image.factory import OUTPUT_FORMAT, generate_image
from service.story.art import _decode_image_content
from service.story.project import ProjectService
from service.story.storage import (
    IMAGE_EXTENSIONS,
    keyframe_image_dir,
    rmdir_if_empty,
    resolve_upload_path,
    unlink_quietly,
)
from utils.env import ENV
from utils.logger import logger

# 关键帧可更新字段白名单
# 注意：image_file/image_width/image_height 不接受客户端直写（防路径穿越），
# 图片仅能经 POST /keyframes/{id}/image 上传端点或后续 AI 生成流内部写入
_KEYFRAME_UPDATABLE = {
    "chapter_no",
    "scene_no",
    "shot_no",
    "name",
    "scene_description",
    "visual_description",
    "camera_description",
    "lighting_description",
    "style_description",
    "prompt",
    "negative_prompt",
    "reference_images",
    "script_id",
    "status",
}

# 关键帧状态白名单（业务层校验）
_KEYFRAME_STATUS = frozenset(s.value for s in StoryKeyframeStatus)

# 创建时可接受的字段集（状态固定 draft）
_KEYFRAME_CREATABLE = _KEYFRAME_UPDATABLE - {"status"}

# 名称长度上限（对齐 schema VARCHAR(200)）
_KEYFRAME_NAME_MAX = 200

# 运行期在途关键帧生图协程注册表（keyframe_id_hex -> asyncio.Task）
_keyframe_tasks: dict[str, asyncio.Task] = {}


def _keyframe_image_directory(project, keyframe) -> str:
    """关键帧图片目录相对路径：story/keyframes/<项目名>/<关键帧名>。

    目录名取清洗后的名称；关键帧未命名时回落 `场景-镜头` 编号，再回落关键帧 id。
    """
    keyframe_fallback = (
        f"{keyframe.scene_no}-{keyframe.shot_no}"
        if keyframe.scene_no is not None and keyframe.shot_no is not None
        else keyframe.id.hex
    )
    return keyframe_image_dir(
        project.title, project.id.hex, keyframe.name or "", keyframe_fallback
    )


class KeyframeService:
    """关键帧业务层：项目属主校验收口。"""

    def __init__(self) -> None:
        self._project_service = ProjectService()

    async def _assert_keyframe_owned(self, session, keyframe_id: uuid.UUID, ctx):
        """关键帧须存在且所属项目归当前用户。"""
        keyframe = await KeyframeRepository(session).get(keyframe_id)
        if keyframe is None:
            bad_except("关键帧不存在")
        await self._project_service._assert_owned(session, keyframe.project_id, ctx)
        return keyframe

    async def _assert_script_in_project(
        self, session, project_id: uuid.UUID, script_id: uuid.UUID | None
    ) -> None:
        """校验溯源剧本（若提供）归属本项目，防跨项目/跨用户剧本引用。

        对齐 VideoService.register 的溯源校验：script_id 为 None 时跳过。
        """
        if script_id is None:
            return
        script = await ScriptRepository(session).get(script_id)
        if script is None or script.project_id != project_id:
            bad_except("溯源剧本不存在或不属于本项目")

    async def _with_characters(self, session, keyframes: list) -> list[dict]:
        """为关键帧列表附加出场角色（含角色名与头像）与导出选择状态，批量查询防 N+1。"""
        kf_ids = [keyframe.id for keyframe in keyframes]
        if not kf_ids:
            return [keyframe.to_dict() for keyframe in keyframes]
        rows = await KeyframeCharacterRepository(session).list_by_keyframes(kf_ids)
        character_ids = {row.character_id for row in rows}
        characters = {}
        if character_ids:
            characters = await CharacterRepository(session).get_many(character_ids)
        grouped: dict[uuid.UUID, list[dict]] = {
            keyframe_id: [] for keyframe_id in kf_ids
        }
        for row in rows:
            character = characters.get(row.character_id)
            entry = row.to_dict()
            entry["character_name"] = character.name if character else None
            entry["character_avatar"] = character.avatar_file if character else None
            grouped[row.keyframe_id].append(entry)
        # 导出选择状态（供前端「导出选择」对话框回显，避免保存即清空）
        asset_repo = ProjectAssetRepository(session)
        selection: dict[uuid.UUID, tuple[bool, int]] = {}
        for project_id in {keyframe.project_id for keyframe in keyframes}:
            for asset_row in await asset_repo.list_by_type(project_id, "keyframe"):
                selection[asset_row.asset_id] = (
                    asset_row.is_selected,
                    asset_row.sort_order,
                )
        # 批量获取生成任务的错误信息（针对 failed 状态的关键帧或异常任务）
        gen_task_ids = {
            keyframe.generation_task_id
            for keyframe in keyframes
            if keyframe.generation_task_id
        }
        task_errors: dict[uuid.UUID, str] = {}
        if gen_task_ids:
            stmt = select(
                StoryGenerationTask.id, StoryGenerationTask.error_message
            ).where(StoryGenerationTask.id.in_(gen_task_ids))
            task_rows = (await session.execute(stmt)).all()
            for tid, err_msg in task_rows:
                if err_msg:
                    task_errors[tid] = err_msg

        items = []
        for keyframe in keyframes:
            data = keyframe.to_dict()
            data["characters"] = grouped.get(keyframe.id, [])
            selected, order = selection.get(keyframe.id, (False, 0))
            data["is_selected"] = selected
            data["selection_order"] = order
            data["error_message"] = (
                task_errors.get(keyframe.generation_task_id)
                if keyframe.generation_task_id
                else None
            )
            items.append(data)
        return items

    async def list(self, ctx, project_id: uuid.UUID, page: int, size: int):
        """项目关键帧列表（含出场角色摘要），按编号升序。"""
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            keyframes, total = await KeyframeRepository(session).list_by_project(
                project_id, page, size
            )
            return await self._with_characters(session, keyframes), total

    async def create(self, ctx, project_id: uuid.UUID, payload) -> dict:
        """创建关键帧：编号冲突校验 + 出场角色登记。"""
        prompt = (payload.prompt or "").strip()
        if not prompt:
            bad_except("正向提示词不能为空")
        if payload.name and len(payload.name) > _KEYFRAME_NAME_MAX:
            bad_except(f"关键帧名称不能超过 {_KEYFRAME_NAME_MAX} 字符")
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            await self._assert_script_in_project(session, project_id, payload.script_id)
            repo = KeyframeRepository(session)
            if (
                payload.scene_no is not None
                and payload.shot_no is not None
                and await repo.exists_numbering(
                    project_id, payload.scene_no, payload.shot_no
                )
            ):
                bad_except(
                    f"场景 {payload.scene_no} 镜头 {payload.shot_no} 编号已被占用"
                )
            fields = {
                key: getattr(payload, key)
                for key in (_KEYFRAME_CREATABLE - {"prompt"})
                if getattr(payload, key) is not None
            }
            keyframe = await repo.create(
                keyframe_id=uuid7(), project_id=project_id, prompt=prompt, **fields
            )
            if payload.characters:
                await self._replace_characters(
                    session, keyframe.id, payload.characters, ctx
                )
            project_repo = ProjectRepository(session)
            project = await project_repo.get(project_id)
            await project_repo.recount_assets(project)
            await session.commit()
            return keyframe.to_dict()

    async def detail(self, ctx, keyframe_id: uuid.UUID) -> dict:
        """关键帧详情（含出场角色）。"""
        async with get_session() as session:
            keyframe = await self._assert_keyframe_owned(session, keyframe_id, ctx)
            items = await self._with_characters(session, [keyframe])
            return items[0]

    async def set_image(
        self, ctx, keyframe_id: uuid.UUID, file_data: bytes, ext: str
    ) -> dict:
        """上传/替换关键帧图片：存入 项目名/关键帧名 目录，旧图提交后清理。"""
        if ext not in IMAGE_EXTENSIONS:
            bad_except(f"不支持的图片类型: {ext}")
        async with get_session() as session:
            keyframe = await self._assert_keyframe_owned(session, keyframe_id, ctx)
            project = await ProjectRepository(session).get(keyframe.project_id)
            old_file = keyframe.image_file
            relative = (
                f"{_keyframe_image_directory(project, keyframe)}/{uuid7().hex}.{ext}"
            )
            target = ENV.upload_dir / relative

            def _save() -> None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(file_data)

            await asyncio.to_thread(_save)
            keyframe.image_file = relative
            keyframe.updated_at = datetime.now(timezone.utc)
            await session.flush()
            await session.commit()
            result = keyframe.to_dict()

        # 提交成功后清理旧图（含其空目录），路径经包含校验，失败仅告警
        if old_file:

            def _cleanup() -> None:
                unlink_quietly(old_file)
                parent = old_file.rsplit("/", 1)[0] if "/" in old_file else None
                if parent:
                    rmdir_if_empty(parent)

            await asyncio.to_thread(_cleanup)
        return result

    async def generate_image(
        self,
        ctx,
        keyframe_id: uuid.UUID,
        size: str | None = None,
        quality: str | None = None,
    ) -> dict:
        """根据提示词与已设置的出场角色（形象立绘与局部描述）生成关键帧图片。"""
        if not ctx.user_id:
            bad_except("关键帧生图仅支持用户通道调用")

        async with get_session() as session:
            keyframe = await self._assert_keyframe_owned(session, keyframe_id, ctx)
            prompt = (keyframe.prompt or "").strip()
            if not prompt:
                bad_except("该关键帧缺少出图提示词，请先编辑补全")
            if keyframe.status == StoryKeyframeStatus.GENERATING.value:
                bad_except("该关键帧正在生成图片中，请稍候")

            project = await ProjectRepository(session).get(keyframe.project_id)
            if project is None:
                bad_except("所属项目不存在")
            if await GenerationTaskRepository(session).has_running(project.id):
                bad_except("本项目已有生成任务进行中，请稍候")

            # 汇总关键帧绑定的出场角色与立绘
            kfc_repo = KeyframeCharacterRepository(session)
            char_repo = CharacterRepository(session)
            art_repo = CharacterArtRepository(session)
            kfc_list = await kfc_repo.list_by_keyframe(keyframe.id)

            reference_images: list[str] = []
            # 保留关键帧本身已配置的参考图（校验本地文件存在性，跳过失效路径）
            if keyframe.reference_images and isinstance(keyframe.reference_images, list):
                for ref in keyframe.reference_images:
                    if isinstance(ref, str) and ref.strip():
                        val = ref.strip()
                        if val.startswith(("http://", "https://", "data:image/")):
                            reference_images.append(val)
                        else:
                            try:
                                if resolve_upload_path(val).is_file():
                                    reference_images.append(val)
                            except Exception:
                                pass

            char_descs: list[str] = []
            for entry in kfc_list:
                character = await char_repo.get(entry.character_id)
                if not character:
                    continue
                char_name = character.name

                art_file: str | None = None
                if entry.character_art_id:
                    art = await art_repo.get(entry.character_art_id)
                    if art and art.image_file:
                        art_file = art.image_file
                if not art_file:
                    arts = await art_repo.list_by_character(character.id)
                    for a in arts:
                        if a.is_primary and a.image_file:
                            art_file = a.image_file
                            break
                    if not art_file and arts and arts[0].image_file:
                        art_file = arts[0].image_file

                if art_file and art_file not in reference_images:
                    try:
                        if resolve_upload_path(art_file).is_file():
                            reference_images.append(art_file)
                    except Exception:
                        pass

                char_detail: list[str] = []
                if character.appearance_prompt and character.appearance_prompt.strip():
                    char_detail.append(f"设定：{character.appearance_prompt.strip()}")
                if entry.character_prompt and entry.character_prompt.strip():
                    char_detail.append(f"镜头状态：{entry.character_prompt.strip()}")

                if char_detail:
                    char_descs.append(f"{char_name}（{'；'.join(char_detail)}）")
                else:
                    char_descs.append(char_name)

            effective_prompt = prompt
            if char_descs:
                effective_prompt = f"{prompt}\n出场角色：{'、'.join(char_descs)}"

            gen_task = await GenerationTaskRepository(session).create(
                task_id=uuid7(),
                project_id=project.id,
                task_type=StoryTaskType.KEYFRAME.value,
                session_id=None,
                target_type="keyframe",
                target_id=keyframe.id,
                provider="image",
                model=CFG.image.model_name,
                prompt=effective_prompt,
                negative_prompt=keyframe.negative_prompt,
                params={
                    "keyframe_id": keyframe.id.hex,
                    "reference_images": reference_images,
                    "size": size,
                    "quality": quality,
                },
                status=StoryTaskStatus.GENERATING.value,
            )

            keyframe.status = StoryKeyframeStatus.GENERATING.value
            keyframe.generation_task_id = gen_task.id
            keyframe.reference_images = reference_images
            keyframe.updated_at = datetime.now(timezone.utc)
            await session.commit()

        # 启动后台生图协程并注册
        task = asyncio.create_task(
            self._run_keyframe_generation(
                gen_task_id=gen_task.id,
                project_id=project.id,
                keyframe_id=keyframe.id,
                prompt=effective_prompt,
                size=size,
                quality=quality,
                reference_images=reference_images,
            )
        )
        _keyframe_tasks[keyframe.id.hex] = task

        async with get_session() as session:
            keyframe = await KeyframeRepository(session).get(keyframe_id)
            items = await self._with_characters(session, [keyframe])
            return items[0]

    async def _run_keyframe_generation(
        self,
        gen_task_id: uuid.UUID,
        project_id: uuid.UUID,
        keyframe_id: uuid.UUID,
        prompt: str,
        size: str | None,
        quality: str | None,
        reference_images: list[str],
    ) -> None:
        async def _update_task(fields: dict) -> None:
            async with get_session() as db:
                row = await GenerationTaskRepository(db).get(gen_task_id)
                if row is not None:
                    await GenerationTaskRepository(db).update_fields(row, fields)
                    await db.commit()

        try:
            await _update_task(
                {
                    "status": StoryTaskStatus.GENERATING.value,
                    "progress": 10,
                    "started_at": datetime.now(timezone.utc),
                }
            )

            contents = await asyncio.to_thread(
                generate_image,
                prompt,
                size,
                quality=quality,
                reference_images=reference_images or None,
            )
            if not contents or not contents[0]:
                raise RuntimeError("图像模型返回空结果")

            data = await asyncio.to_thread(_decode_image_content, contents[0])

            old_file: str | None = None
            rel_path: str = ""
            async with get_session() as db:
                keyframe = await KeyframeRepository(db).get(keyframe_id)
                project = await ProjectRepository(db).get(project_id)
                if keyframe is None or project is None:
                    await _update_task(
                        {
                            "status": StoryTaskStatus.CANCELLED.value,
                            "finished_at": datetime.now(timezone.utc),
                            "error_message": "关键帧或项目已被删除",
                        }
                    )
                    return

                rel_dir = _keyframe_image_directory(project, keyframe)
                filename = f"{uuid7().hex}.{OUTPUT_FORMAT}"
                rel_path = f"{rel_dir}/{filename}"
                target = ENV.upload_dir / rel_path

                def _save() -> None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)

                await asyncio.to_thread(_save)

                old_file = keyframe.image_file
                keyframe.image_file = rel_path
                keyframe.status = StoryKeyframeStatus.DONE.value
                keyframe.updated_at = datetime.now(timezone.utc)
                await db.commit()

            if old_file:
                def _cleanup() -> None:
                    unlink_quietly(old_file)
                    parent = old_file.rsplit("/", 1)[0] if "/" in old_file else None
                    if parent:
                        rmdir_if_empty(parent)

                await asyncio.to_thread(_cleanup)

            await _update_task(
                {
                    "status": StoryTaskStatus.SUCCEEDED.value,
                    "progress": 100,
                    "result_image_file": rel_path,
                    "finished_at": datetime.now(timezone.utc),
                }
            )
            logger.info(
                f"[STORY] 关键帧图片生成完成 keyframe={keyframe_id.hex} file={rel_path}"
            )
        except asyncio.CancelledError:
            logger.warning(
                f"[STORY] 关键帧图片生成被取消 keyframe={keyframe_id.hex}"
            )
            try:
                async with get_session() as db:
                    keyframe = await KeyframeRepository(db).get(keyframe_id)
                    if (
                        keyframe is not None
                        and keyframe.status == StoryKeyframeStatus.GENERATING.value
                    ):
                        keyframe.status = StoryKeyframeStatus.FAILED.value
                        keyframe.updated_at = datetime.now(timezone.utc)
                        await db.commit()
                await _update_task(
                    {
                        "status": StoryTaskStatus.CANCELLED.value,
                        "finished_at": datetime.now(timezone.utc),
                        "error_message": "用户主动中止生成",
                    }
                )
            except Exception as inner_exc:
                logger.error(
                    f"[STORY] 关键帧取消终态落库失败 keyframe={keyframe_id.hex}: {inner_exc}"
                )
            raise
        except Exception as exc:
            logger.error(
                f"[STORY] 关键帧图片生成失败 keyframe={keyframe_id.hex}: {exc}"
            )
            async with get_session() as db:
                keyframe = await KeyframeRepository(db).get(keyframe_id)
                if keyframe is not None:
                    keyframe.status = StoryKeyframeStatus.FAILED.value
                    keyframe.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            await _update_task(
                {
                    "status": StoryTaskStatus.FAILED.value,
                    "finished_at": datetime.now(timezone.utc),
                    "error_message": str(exc)[:500],
                }
            )
        finally:
            _keyframe_tasks.pop(keyframe_id.hex, None)

    async def stop(self, ctx, keyframe_id: uuid.UUID) -> bool:
        """中断/取消关键帧在途生成任务，释放项目级生成互斥锁。"""
        if not ctx.user_id:
            bad_except("关键帧操作仅支持用户通道调用")
        cancelled = False
        async with get_session() as session:
            keyframe = await self._assert_keyframe_owned(session, keyframe_id, ctx)
            task_id = keyframe.generation_task_id

            # 1. 尝试取消内存中运行的 asyncio 任务
            task = _keyframe_tasks.get(keyframe_id.hex)
            if task and not task.done():
                task.cancel()
                cancelled = True

            # 2. 状态落库：若当前仍为 generating，统一置为 failed 终态
            if keyframe.status == StoryKeyframeStatus.GENERATING.value:
                keyframe.status = StoryKeyframeStatus.FAILED.value
                keyframe.updated_at = datetime.now(timezone.utc)
                cancelled = True

            task_repo = GenerationTaskRepository(session)
            if task_id:
                task_row = await task_repo.get(task_id)
                if task_row and task_row.status in GenerationTaskRepository.RUNNING_STATUSES:
                    await task_repo.update_fields(
                        task_row,
                        {
                            "status": StoryTaskStatus.CANCELLED.value,
                            "error_message": "用户主动中止生成",
                            "finished_at": datetime.now(timezone.utc),
                        },
                    )
                    cancelled = True

            # 3. 兜底清理本项目下该关键帧关联的历史残留在途生成任务，保证释放 has_running 互斥
            stmt = select(StoryGenerationTask).where(
                StoryGenerationTask.project_id == keyframe.project_id,
                StoryGenerationTask.target_id == keyframe.id,
                StoryGenerationTask.status.in_(GenerationTaskRepository.RUNNING_STATUSES),
            )
            orphan_tasks = (await session.scalars(stmt)).all()
            for ot in orphan_tasks:
                await task_repo.update_fields(
                    ot,
                    {
                        "status": StoryTaskStatus.CANCELLED.value,
                        "error_message": "用户主动中止生成",
                        "finished_at": datetime.now(timezone.utc),
                    },
                )
                cancelled = True

            await session.commit()
            logger.info(
                f"[STORY] 关键帧生成任务已中止 keyframe={keyframe_id.hex} cancelled={cancelled}"
            )
            return cancelled

    async def _relocate_image(self, session, project, keyframe, old_name) -> None:
        """关键帧改名后把图片迁至新名称目录（缺失文件保留原路径，不阻断改名）。"""
        if not keyframe.image_file:
            return
        old_dir = keyframe_image_dir(
            project.title,
            project.id.hex,
            old_name or "",
            (
                f"{keyframe.scene_no}-{keyframe.shot_no}"
                if keyframe.scene_no is not None and keyframe.shot_no is not None
                else keyframe.id.hex
            ),
        )
        new_dir = _keyframe_image_directory(project, keyframe)
        if old_dir == new_dir:
            return
        try:
            src = resolve_upload_path(keyframe.image_file)
        except Exception:
            logger.warning(
                f"[STORY] 关键帧图片路径非法，跳过迁移: {keyframe.image_file}"
            )
            return
        new_rel = f"{new_dir}/{Path(keyframe.image_file).name}"

        def _move() -> bool:
            if not src.is_file():
                logger.warning(
                    f"[STORY] 关键帧图片缺失，跳过迁移: {keyframe.image_file}"
                )
                return False
            try:
                (ENV.upload_dir / new_dir).mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(ENV.upload_dir / new_rel))
                return True
            except OSError as exc:
                logger.warning(
                    f"[STORY] 关键帧图片迁移失败: {keyframe.image_file}: {exc}"
                )
                return False

        moved = await asyncio.to_thread(_move)
        if moved:
            keyframe.image_file = new_rel
            keyframe.updated_at = datetime.now(timezone.utc)
            await session.flush()

    async def update(self, ctx, keyframe_id: uuid.UUID, payload) -> dict:
        """编辑关键帧字段（白名单内显式传入），编号变更时重新校验冲突。"""
        async with get_session() as session:
            keyframe = await self._assert_keyframe_owned(session, keyframe_id, ctx)
            fields = {
                key: value
                for key, value in payload.model_dump(exclude_unset=True).items()
                if key in _KEYFRAME_UPDATABLE
            }
            if not fields:
                bad_except("没有可更新的字段")
            if "status" in fields and fields["status"] not in _KEYFRAME_STATUS:
                bad_except(f"关键帧状态非法: {fields['status']}")
            if "prompt" in fields and not (fields["prompt"] or "").strip():
                bad_except("正向提示词不能为空")
            if (
                "name" in fields
                and fields["name"]
                and len(fields["name"]) > _KEYFRAME_NAME_MAX
            ):
                bad_except(f"关键帧名称不能超过 {_KEYFRAME_NAME_MAX} 字符")
            if "script_id" in fields:
                await self._assert_script_in_project(
                    session, keyframe.project_id, fields["script_id"]
                )
            scene_no = fields.get("scene_no", keyframe.scene_no)
            shot_no = fields.get("shot_no", keyframe.shot_no)
            if (
                scene_no is not None
                and shot_no is not None
                and (scene_no != keyframe.scene_no or shot_no != keyframe.shot_no)
                and await KeyframeRepository(session).exists_numbering(
                    keyframe.project_id, scene_no, shot_no, exclude_id=keyframe_id
                )
            ):
                bad_except(f"场景 {scene_no} 镜头 {shot_no} 编号已被占用")
            old_name = keyframe.name
            old_status = keyframe.status
            await KeyframeRepository(session).update_fields(keyframe, fields)
            project_repo = ProjectRepository(session)
            if "name" in fields and (fields["name"] or "") != (old_name or ""):
                project = await project_repo.get(keyframe.project_id)
                await self._relocate_image(session, project, keyframe, old_name)
            new_status = fields.get("status", old_status)
            if new_status != old_status:
                # 归档即退出统计与导出：移除导出选择行并重算项目计数
                if new_status == StoryKeyframeStatus.ARCHIVED:
                    await ProjectAssetRepository(session).remove(
                        keyframe.project_id, "keyframe", keyframe_id
                    )
                if StoryKeyframeStatus.ARCHIVED in (old_status, new_status):
                    project = await project_repo.get(keyframe.project_id)
                    if project is not None:
                        await project_repo.recount_assets(project)
            await session.commit()
            return keyframe.to_dict()

    async def _replace_characters(
        self, session, keyframe_id: uuid.UUID, entries: list, ctx
    ) -> None:
        """整体替换出场角色：校验角色归属当前用户（跨用户按不存在处理）。"""
        char_repo = CharacterRepository(session)
        art_repo = CharacterArtRepository(session)
        normalized: list[dict] = []
        seen_chars: set[uuid.UUID] = set()
        for entry in entries:
            if entry.character_id in seen_chars:
                bad_except("同一角色不能在关键帧中重复出场")
            seen_chars.add(entry.character_id)
            character = await char_repo.get(entry.character_id)
            if character is None or character.user_id != ctx.user_id:
                bad_except("角色不存在")
            if entry.character_art_id is not None:
                art = await art_repo.get(entry.character_art_id)
                # 参考立绘须存在且属于该角色（角色已校验归属当前用户，蕴含立绘归属）
                if art is None or art.character_id != entry.character_id:
                    bad_except("参考立绘不存在或不属于该角色")
            normalized.append(
                {
                    "character_id": entry.character_id,
                    "character_art_id": entry.character_art_id,
                    "role": entry.role,
                    "character_prompt": entry.character_prompt,
                }
            )
        await KeyframeCharacterRepository(session).replace_for_keyframe(
            keyframe_id, normalized
        )

    async def set_characters(self, ctx, keyframe_id: uuid.UUID, entries: list) -> dict:
        """整体设置关键帧出场角色（含参考立绘与局部描述），返回关键帧详情。"""
        async with get_session() as session:
            keyframe = await self._assert_keyframe_owned(session, keyframe_id, ctx)
            await self._replace_characters(session, keyframe_id, entries, ctx)
            await session.commit()
            items = await self._with_characters(session, [keyframe])
            return items[0]

    async def delete(self, ctx, keyframe_id: uuid.UUID) -> None:
        """删除关键帧：清理出场角色与编排引用，重算项目计数。"""
        async with get_session() as session:
            keyframe = await self._assert_keyframe_owned(session, keyframe_id, ctx)
            project = await ProjectRepository(session).get(keyframe.project_id)
            image_file = keyframe.image_file
            image_dir = (
                _keyframe_image_directory(project, keyframe) if image_file else None
            )
            await KeyframeCharacterRepository(session).delete_by_keyframe(keyframe_id)
            await ProjectAssetRepository(session).remove(
                keyframe.project_id, "keyframe", keyframe_id
            )
            await KeyframeRepository(session).delete(keyframe)
            project_repo = ProjectRepository(session)
            await project_repo.recount_assets(project)
            await session.commit()
        # 提交成功后按 DB 记录精确清理图片与空目录（不整目录 rmtree，防误删同名目录）
        if image_file and image_dir:
            project_dir = image_dir.rsplit("/", 1)[0]

            def _cleanup() -> None:
                unlink_quietly(image_file)
                rmdir_if_empty(image_dir)
                rmdir_if_empty(project_dir)

            await asyncio.to_thread(_cleanup)

    async def set_selection(
        self, ctx, project_id: uuid.UUID, keyframe_ids: "list[uuid.UUID]"
    ) -> "list[dict]":
        """整体设置项目的导出选中关键帧（编排表替换），空列表清空选择。

        传入的关键帧必须全部归属本项目；按传入顺序记录导出顺序。
        """
        # 入参保序去重：防重复 id 触发 UNIQUE(project_id, asset_type, asset_id) 返回 500
        keyframe_ids = list(dict.fromkeys(keyframe_ids))
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            kf_repo = KeyframeRepository(session)
            for keyframe_id in keyframe_ids:
                keyframe = await kf_repo.get(keyframe_id)
                if keyframe is None or keyframe.project_id != project_id:
                    bad_except("关键帧不存在或不属于本项目")
                if keyframe.status == StoryKeyframeStatus.ARCHIVED:
                    bad_except("已归档关键帧不可参与导出选择，请先取消归档")
            asset_repo = ProjectAssetRepository(session)
            for row in await asset_repo.list_by_type(project_id, "keyframe"):
                await asset_repo.remove(project_id, "keyframe", row.asset_id)
            for index, keyframe_id in enumerate(keyframe_ids):
                await asset_repo.add(
                    uuid7(), project_id, "keyframe", keyframe_id, sort_order=index
                )
            rows = await asset_repo.list_by_type(project_id, "keyframe")
            await session.commit()
            return [row.to_dict() for row in rows]
