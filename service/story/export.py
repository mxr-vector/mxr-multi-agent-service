"""
剧本模块导出包业务层：统一装配"角色+剧本+关键帧"不可变快照并打包为 ZIP 素材包。

- 导出包整合剧本文档、人物立绘高清图与人设信息、关键帧图片与分镜提示词；
- 导出格式全局统一，target_platform 仅自由文本备注；
- 装配口径：当前剧本 + 出演角色（含选中立绘，未选中时回落主立绘）+ 关键帧；
  快照生成后不受后续资产变更影响；
- 版本号按 (project_id, export_type) 递增。
"""

import asyncio
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from uuid_utils.compat import uuid7

from agent.constants.enums.story import StoryKeyframeStatus
from database.postgre_client import get_session
from database.story.character import CharacterArtRepository, CharacterRepository
from database.story.project import (
    ExportPackageRepository,
    KeyframeCharacterRepository,
    KeyframeRepository,
    ProjectAssetRepository,
    ScriptRepository,
)
from exception.bad_except import bad_except
from service.story.project import ProjectService
from service.story.storage import resolve_upload_path
from utils.id import format_id
from utils.logger import logger

# 导出模板版本（统一格式，无平台差异）
EXPORT_TEMPLATE_VERSION = "unified-v1"

# 导出包名称长度上限（对齐 schema VARCHAR(200)）
_EXPORT_NAME_MAX = 200

# 目录与文件名非法字符正则
_UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _safe_filename(name: str | None, fallback: str = "unnamed") -> str:
    """清洗文件名/目录名中的非法字符。"""
    cleaned = _UNSAFE_FILENAME_RE.sub("_", (name or "").strip()).strip(". ")
    return cleaned or fallback


class ExportService:
    """导出包业务层：项目属主校验收口。"""

    def __init__(self) -> None:
        self._project_service = ProjectService()

    async def export(self, ctx, project_id: uuid.UUID, payload) -> dict:
        """装配并保存导出包快照（不可变）。"""
        async with get_session() as session:
            project = await self._project_service._assert_owned(
                session, project_id, ctx
            )
            script = await ScriptRepository(session).get_current(project_id)
            if script is None:
                bad_except("项目还没有当前剧本，无法导出")
            asset_repo = ProjectAssetRepository(session)
            char_repo = CharacterRepository(session)
            art_repo = CharacterArtRepository(session)

            # 出演角色：优先取编排表选中立绘，未选中时回落主立绘
            selected_art_ids = {
                row.asset_id
                for row in await asset_repo.list_by_type(
                    project_id, "character_art", selected_only=True
                )
            }
            cast_rows = await asset_repo.list_by_type(project_id, "character")
            cast_char_ids = {row.asset_id for row in cast_rows}
            # 批量装配（各一次 IN 查询）：角色本体 + 全部立绘，消除嵌套 N+1
            cast_characters = await char_repo.get_many(cast_char_ids)
            cast_arts = await art_repo.list_by_characters(cast_char_ids)
            characters_payload: list[dict] = []
            for row in cast_rows:
                character = cast_characters.get(row.asset_id)
                if character is None:
                    continue
                arts = cast_arts.get(character.id, [])
                chosen = (
                    [art for art in arts if art.id in selected_art_ids]
                    or [art for art in arts if art.art_type == "character_sheet"]
                    or [art for art in arts if art.is_primary]
                    or (arts[:1] if arts else [])
                )
                data = character.to_dict()
                data["sort_order"] = row.sort_order
                data["arts"] = [art.to_dict() for art in chosen]
                characters_payload.append(data)

            # 被选关键帧（排除归档），附出场角色名
            kf_repo = KeyframeRepository(session)
            kfc_repo = KeyframeCharacterRepository(session)
            kf_sel_rows = await asset_repo.list_by_type(
                project_id, "keyframe", selected_only=True
            )
            if kf_sel_rows:
                kf_ids = [row.asset_id for row in kf_sel_rows]
                sort_order_map = {row.asset_id: row.sort_order for row in kf_sel_rows}
            else:
                # 若未在编排表中单独挑选，默认导出项目下全部未归档关键帧（按章节/场景/镜头排序）
                all_kfs, _ = await kf_repo.list_by_project(project_id, page=1, size=1000)
                active_kfs = [
                    kf for kf in all_kfs if kf.status != StoryKeyframeStatus.ARCHIVED
                ]
                kf_ids = [kf.id for kf in active_kfs]
                sort_order_map = {kf.id: idx for idx, kf in enumerate(active_kfs)}

            # 批量装配（各一次 IN 查询）：关键帧本体 + 出场角色行 + 角色名
            keyframes_map = await kf_repo.get_many(set(kf_ids))
            kfc_rows = await kfc_repo.list_by_keyframes(kf_ids)
            kfc_characters = await char_repo.get_many(
                {row.character_id for row in kfc_rows}
            )
            kfc_by_keyframe: dict[uuid.UUID, list[dict]] = {}
            for kfc in kfc_rows:
                character = kfc_characters.get(kfc.character_id)
                entry = kfc.to_dict()
                entry["character_name"] = character.name if character else None
                kfc_by_keyframe.setdefault(kfc.keyframe_id, []).append(entry)

            # 若项目未单独登记出演角色，但关键帧中有引用角色，作为兜底补全
            if not characters_payload and kfc_rows:
                kfc_char_ids = {row.character_id for row in kfc_rows}
                kfc_all_chars = await char_repo.get_many(kfc_char_ids)
                kfc_all_arts = await art_repo.list_by_characters(kfc_char_ids)
                for idx, c_id in enumerate(kfc_char_ids):
                    ch = kfc_all_chars.get(c_id)
                    if ch is None:
                        continue
                    arts = kfc_all_arts.get(ch.id, [])
                    chosen = (
                        [art for art in arts if art.art_type == "character_sheet"]
                        or [art for art in arts if art.is_primary]
                        or (arts[:1] if arts else [])
                    )
                    c_data = ch.to_dict()
                    c_data["sort_order"] = idx
                    c_data["arts"] = [art.to_dict() for art in chosen]
                    characters_payload.append(c_data)

            keyframes_payload: list[dict] = []
            for kf_id in kf_ids:
                keyframe = keyframes_map.get(kf_id)
                if keyframe is None or keyframe.status == StoryKeyframeStatus.ARCHIVED:
                    continue
                kf_data = keyframe.to_dict()
                kf_data["characters"] = kfc_by_keyframe.get(keyframe.id, [])
                kf_data["sort_order"] = sort_order_map.get(keyframe.id, 0)
                keyframes_payload.append(kf_data)

            payload_json = {
                "project": {
                    "id": format_id(project.id),
                    "title": project.title,
                    "description": project.description,
                },
                "script": script.to_dict(),
                "characters": characters_payload,
                "keyframes": keyframes_payload,
            }
            text = self._render_text(
                project.title, script, characters_payload, keyframes_payload
            )
            repo = ExportPackageRepository(session)
            version = await repo.next_version(project_id, "video_input")
            name = (payload.name or "").strip() if payload.name else ""
            if name:
                if len(name) > _EXPORT_NAME_MAX:
                    bad_except(f"导出包名称不能超过 {_EXPORT_NAME_MAX} 字符")
            else:
                suffix = f" 导出 v{version}"
                name = project.title[: _EXPORT_NAME_MAX - len(suffix)] + suffix
            package = await repo.create(
                package_id=uuid7(),
                project_id=project_id,
                name=name,
                payload=payload_json,
                prompt_text=text,
                copy_text=text,
                markdown_text=text,
                version=version,
                target_platform=payload.target_platform,
                script_id=script.id,
                template_version=EXPORT_TEMPLATE_VERSION,
            )
            await session.commit()
            return package.to_dict()

    @staticmethod
    def _render_text(
        project_title: str,
        script,
        characters: list[dict],
        keyframes: list[dict],
    ) -> str:
        """把快照渲染为导出包内的汇总说明文本。"""
        lines = [f"# 《{project_title}》视频生成素材包", ""]

        lines.append(f"## 一、剧本（v{script.version}）")
        lines.append("")
        if script.title:
            lines.append(f"标题：{script.title}")
            lines.append("")
        lines.append(script.content)
        lines.append("")

        lines.append("## 二、角色")
        lines.append("")
        if not characters:
            lines.append("（无出演角色）")
        for character in characters:
            lines.append(f"### {character['name']}")
            if character.get("role_type"):
                lines.append(f"- 角色类型：{character['role_type']}")
            if character.get("profile"):
                lines.append(
                    f"- 人设：{json.dumps(character['profile'], ensure_ascii=False)}"
                )
            if character.get("style"):
                lines.append(
                    f"- 视觉风格：{json.dumps(character['style'], ensure_ascii=False)}"
                )
            if character.get("appearance_prompt"):
                lines.append(f"- 外观描述：{character['appearance_prompt']}")
            art_files = [art["image_file"] for art in character.get("arts", [])]
            if art_files:
                lines.append(f"- 参考立绘：{', '.join(art_files)}")
            lines.append("")

        lines.append("## 三、关键帧")
        lines.append("")
        if not keyframes:
            lines.append("（无选中关键帧）")
        for keyframe in keyframes:
            title = keyframe.get("name") or (
                f"场景{keyframe.get('scene_no')}-镜头{keyframe.get('shot_no')}"
            )
            lines.append(f"### {title}")
            for label, key in (
                ("场景描述", "scene_description"),
                ("画面", "visual_description"),
                ("镜头", "camera_description"),
                ("光线", "lighting_description"),
                ("风格", "style_description"),
            ):
                if keyframe.get(key):
                    lines.append(f"- {label}：{keyframe[key]}")
            lines.append(f"- 正向提示词：{keyframe['prompt']}")
            if keyframe.get("negative_prompt"):
                lines.append(f"- 负向提示词：{keyframe['negative_prompt']}")
            characters_in_shot = keyframe.get("characters") or []
            if characters_in_shot:
                names = "、".join(
                    entry.get("character_name") or "未知角色"
                    for entry in characters_in_shot
                )
                lines.append(f"- 出场角色：{names}")
            lines.append("")

        return "\n".join(lines)

    async def list(self, ctx, project_id: uuid.UUID, page: int, size: int):
        """项目导出包列表，版本倒序。"""
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            items, total = await ExportPackageRepository(session).list_by_project(
                project_id, page, size
            )
            return [item.to_dict() for item in items], total

    async def detail(self, ctx, package_id: uuid.UUID) -> dict:
        """导出包详情（含快照），须为本人项目下的导出包。"""
        async with get_session() as session:
            package = await ExportPackageRepository(session).get(package_id)
            if package is None:
                bad_except("导出包不存在")
            await self._project_service._assert_owned(session, package.project_id, ctx)
            return package.to_dict()

    async def build_zip(self, ctx, package_id: uuid.UUID) -> tuple[io.BytesIO, str]:
        """按导出包快照装配 ZIP 压缩包（包含剧本、人物立绘、关键帧及完整说明）。"""
        async with get_session() as session:
            package = await ExportPackageRepository(session).get(package_id)
            if package is None:
                bad_except("导出包不存在")
            await self._project_service._assert_owned(session, package.project_id, ctx)

            payload = dict(package.payload or {})

            # 关键帧补全（兜底逻辑：若快照中关键帧为空，尝试从项目未归档关键帧装配）
            if not payload.get("keyframes"):
                kf_repo = KeyframeRepository(session)
                char_repo = CharacterRepository(session)
                kfc_repo = KeyframeCharacterRepository(session)
                all_kfs, _ = await kf_repo.list_by_project(
                    package.project_id, page=1, size=1000
                )
                active_kfs = [
                    kf for kf in all_kfs if kf.status != StoryKeyframeStatus.ARCHIVED
                ]
                if active_kfs:
                    kf_ids = [kf.id for kf in active_kfs]
                    keyframes_map = await kf_repo.get_many(set(kf_ids))
                    kfc_rows = await kfc_repo.list_by_keyframes(kf_ids)
                    kfc_characters = await char_repo.get_many(
                        {row.character_id for row in kfc_rows}
                    )
                    kfc_by_keyframe: dict[uuid.UUID, list[dict]] = {}
                    for kfc in kfc_rows:
                        character = kfc_characters.get(kfc.character_id)
                        entry = kfc.to_dict()
                        entry["character_name"] = character.name if character else None
                        kfc_by_keyframe.setdefault(kfc.keyframe_id, []).append(entry)
                    kfs_payload = []
                    for idx, kf in enumerate(active_kfs):
                        kd = kf.to_dict()
                        kd["characters"] = kfc_by_keyframe.get(kf.id, [])
                        kd["sort_order"] = idx
                        kfs_payload.append(kd)
                    payload["keyframes"] = kfs_payload

            # 出演角色补全（兜底逻辑：若快照中角色为空，尝试从项目出演表或关键帧装配）
            if not payload.get("characters"):
                asset_repo = ProjectAssetRepository(session)
                char_repo = CharacterRepository(session)
                art_repo = CharacterArtRepository(session)
                cast_rows = await asset_repo.list_by_type(package.project_id, "character")
                cast_char_ids = {row.asset_id for row in cast_rows}
                if not cast_char_ids and payload.get("keyframes"):
                    for kf in payload["keyframes"]:
                        for ch in kf.get("characters") or []:
                            if ch.get("character_id"):
                                try:
                                    cast_char_ids.add(uuid.UUID(ch["character_id"]))
                                except Exception:
                                    pass
                if cast_char_ids:
                    cast_characters = await char_repo.get_many(cast_char_ids)
                    cast_arts = await art_repo.list_by_characters(cast_char_ids)
                    chars_payload = []
                    for idx, c_id in enumerate(cast_char_ids):
                        ch = cast_characters.get(c_id)
                        if ch:
                            cd = ch.to_dict()
                            arts = cast_arts.get(ch.id, [])
                            chosen = (
                                [art for art in arts if art.art_type == "character_sheet"]
                                or [art for art in arts if art.is_primary]
                                or (arts[:1] if arts else [])
                            )
                            cd["sort_order"] = idx
                            cd["arts"] = [art.to_dict() for art in chosen]
                            chars_payload.append(cd)
                    payload["characters"] = chars_payload

            buffer = await asyncio.to_thread(self._create_zip_archive, package, payload)
            safe_name = _safe_filename(package.name, "story_export")
            filename = f"{safe_name}.zip"
            return buffer, filename

    @staticmethod
    def _create_zip_archive(package, payload: dict) -> io.BytesIO:
        """同步构建 ZIP 内存流，包含剧本、人物立绘、关键帧及完整说明。"""
        buffer = io.BytesIO()
        project = payload.get("project") or {}
        project_title = project.get("title") or package.name
        script = payload.get("script") or {}
        characters = payload.get("characters") or []
        keyframes = payload.get("keyframes") or []

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. 剧本文件（同时提供 Markdown 与纯文本格式）
            script_version = script.get("version", 1)
            script_title = script.get("title") or "未命名剧本"
            script_content = script.get("content") or "（无剧本内容）"

            script_md = (
                f"# 《{project_title}》剧本\n\n"
                f"- **版本**：v{script_version}\n"
                f"- **剧本标题**：{script_title}\n\n"
                f"---\n\n"
                f"{script_content}\n"
            )
            zf.writestr("剧本/剧本.md", script_md)

            script_txt = (
                f"《{project_title}》剧本（v{script_version}）\n"
                f"标题：{script_title}\n"
                f"{'=' * 50}\n\n"
                f"{script_content}\n"
            )
            zf.writestr("剧本/剧本.txt", script_txt)

            # 2. 人物立绘
            char_overview_lines = [
                f"# 《{project_title}》出演角色总览",
                f"共 {len(characters)} 位角色",
                "",
            ]
            for idx, char in enumerate(characters, start=1):
                char_name = _safe_filename(char.get("name"), f"角色_{idx}")
                role_type = char.get("role_type") or "未指定"
                char_dir = f"人物立绘/{idx:02d}_{char_name}"

                char_overview_lines.append(f"## {idx}. {char.get('name') or '未命名'}")
                char_overview_lines.append(f"- 角色类型：{role_type}")
                if char.get("appearance_prompt"):
                    char_overview_lines.append(f"- 外观描述：{char['appearance_prompt']}")
                if char.get("profile"):
                    profile_str = (
                        char["profile"]
                        if isinstance(char["profile"], str)
                        else json.dumps(char["profile"], ensure_ascii=False)
                    )
                    char_overview_lines.append(f"- 人设背景：{profile_str}")
                char_overview_lines.append("")

                # 角色详细信息文件
                char_info_lines = [
                    f"角色名称：{char.get('name') or '未命名'}",
                    f"角色类型：{role_type}",
                ]
                if char.get("appearance_prompt"):
                    char_info_lines.append(f"外观描述：{char['appearance_prompt']}")
                if char.get("profile"):
                    profile_str = (
                        char["profile"]
                        if isinstance(char["profile"], str)
                        else json.dumps(char["profile"], ensure_ascii=False)
                    )
                    char_info_lines.append(f"人设背景：{profile_str}")
                if char.get("style"):
                    style_str = (
                        char["style"]
                        if isinstance(char["style"], str)
                        else json.dumps(char["style"], ensure_ascii=False)
                    )
                    char_info_lines.append(f"视觉风格：{style_str}")
                zf.writestr(f"{char_dir}/角色信息.txt", "\n".join(char_info_lines))

                # 角色立绘图片
                arts = char.get("arts") or []
                art_count = 0
                for art_idx, art in enumerate(arts, start=1):
                    art_file = art.get("image_file")
                    if not art_file:
                        continue
                    try:
                        abs_path = resolve_upload_path(art_file)
                        if abs_path.is_file():
                            data = abs_path.read_bytes()
                            ext = abs_path.suffix or ".png"
                            art_name = _safe_filename(
                                art.get("name") or art.get("art_type") or "立绘",
                                f"art_{art_idx}",
                            )
                            is_pri = "_主立绘" if art.get("is_primary") else ""
                            zf.writestr(
                                f"{char_dir}/{art_idx:02d}_{art_name}{is_pri}{ext}",
                                data,
                            )
                            art_count += 1
                    except Exception as e:
                        logger.warning(f"导出包添加角色立绘失败: {art_file}: {e}")

                # 如果 arts 为空，尝试添加角色头像 avatar_file
                if art_count == 0 and char.get("avatar_file"):
                    try:
                        abs_path = resolve_upload_path(char["avatar_file"])
                        if abs_path.is_file():
                            ext = abs_path.suffix or ".png"
                            zf.writestr(f"{char_dir}/01_头像{ext}", abs_path.read_bytes())
                    except Exception as e:
                        logger.warning(
                            f"导出包添加角色头像失败: {char['avatar_file']}: {e}"
                        )

            zf.writestr("人物立绘/角色总览.txt", "\n".join(char_overview_lines))

            # 3. 关键帧
            kf_overview_lines = [
                f"# 《{project_title}》关键帧总览",
                f"共 {len(keyframes)} 个关键帧",
                "",
            ]
            for idx, kf in enumerate(keyframes, start=1):
                scene_no = kf.get("scene_no") if kf.get("scene_no") is not None else 1
                shot_no = kf.get("shot_no") if kf.get("shot_no") is not None else idx
                kf_title = kf.get("name") or f"场景{scene_no}-镜头{shot_no}"
                safe_title = _safe_filename(kf.get("name") or "", "")
                prefix = f"{idx:02d}_场景{scene_no}-镜头{shot_no}"
                if safe_title:
                    prefix = f"{prefix}_{safe_title}"

                kf_overview_lines.append(f"## {idx}. {kf_title}")
                if kf.get("scene_description"):
                    kf_overview_lines.append(f"- 场景描述：{kf['scene_description']}")
                if kf.get("visual_description"):
                    kf_overview_lines.append(f"- 画面描述：{kf['visual_description']}")
                if kf.get("camera_description"):
                    kf_overview_lines.append(f"- 镜头运镜：{kf['camera_description']}")
                if kf.get("prompt"):
                    kf_overview_lines.append(f"- 正向提示词：{kf['prompt']}")
                kf_overview_lines.append("")

                # 关键帧独立提示词文件
                kf_info_lines = [
                    f"关键帧：{kf_title}",
                    f"镜头定位：场景 {scene_no}，镜头 {shot_no}",
                ]
                for label, key in (
                    ("场景描述", "scene_description"),
                    ("画面描述", "visual_description"),
                    ("镜头运镜", "camera_description"),
                    ("光线说明", "lighting_description"),
                    ("画面风格", "style_description"),
                ):
                    if kf.get(key):
                        kf_info_lines.append(f"{label}：{kf[key]}")

                chars_in_shot = kf.get("characters") or []
                if chars_in_shot:
                    names = "、".join(
                        entry.get("character_name") or "未知角色"
                        for entry in chars_in_shot
                    )
                    kf_info_lines.append(f"出场角色：{names}")

                kf_info_lines.append(f"\n【正向提示词】\n{kf.get('prompt') or ''}")
                if kf.get("negative_prompt"):
                    kf_info_lines.append(f"\n【负向提示词】\n{kf['negative_prompt']}")

                zf.writestr(f"关键帧/{prefix}_提示词.txt", "\n".join(kf_info_lines))

                # 关键帧图片文件
                image_file = kf.get("image_file")
                if image_file:
                    try:
                        abs_path = resolve_upload_path(image_file)
                        if abs_path.is_file():
                            data = abs_path.read_bytes()
                            ext = abs_path.suffix or ".png"
                            zf.writestr(f"关键帧/{prefix}{ext}", data)
                    except Exception as e:
                        logger.warning(f"导出包添加关键帧图片失败: {image_file}: {e}")

            zf.writestr("关键帧/关键帧总览.txt", "\n".join(kf_overview_lines))

            # 4. 根目录汇总与结构化清单
            prompt_text = package.prompt_text or package.copy_text or ""
            zf.writestr("完整提示词与说明.txt", prompt_text)
            zf.writestr(
                "manifest.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )

        buffer.seek(0)
        return buffer
