"""
剧本模块关键帧业务层：五段式描述维护、编号冲突校验与出场角色登记。

- (场景号, 镜头号) 组合项目内唯一（编号均为非空时参与判定）；
- 出场角色按关键帧整体替换（含参考立绘与镜头内局部描述）；
- 关键帧可附带一张图片，按 项目名/关键帧名 目录存储，改名时迁移；
- 删除关键帧同步清理出场角色与导出编排引用，并重算项目计数。
"""

import asyncio
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from uuid_utils.compat import uuid7

from database.postgre_client import get_session
from database.story.character import CharacterArtRepository, CharacterRepository
from database.story.project import (
    KeyframeCharacterRepository,
    KeyframeRepository,
    ProjectAssetRepository,
    ProjectRepository,
    ScriptRepository,
)
from exception.bad_except import bad_except
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
_KEYFRAME_STATUS = {"draft", "generating", "done", "failed", "archived"}

# 创建时可接受的字段集（状态固定 draft）
_KEYFRAME_CREATABLE = _KEYFRAME_UPDATABLE - {"status"}

# 名称长度上限（对齐 schema VARCHAR(200)）
_KEYFRAME_NAME_MAX = 200


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
        items = []
        for keyframe in keyframes:
            data = keyframe.to_dict()
            data["characters"] = grouped.get(keyframe.id, [])
            selected, order = selection.get(keyframe.id, (False, 0))
            data["is_selected"] = selected
            data["selection_order"] = order
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
                if new_status == "archived":
                    await ProjectAssetRepository(session).remove(
                        keyframe.project_id, "keyframe", keyframe_id
                    )
                if "archived" in (old_status, new_status):
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
        for entry in entries:
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
                if keyframe.status == "archived":
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
