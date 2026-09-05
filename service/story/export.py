"""
剧本模块导出包业务层：统一装配"角色+剧本+关键帧"不可变快照。

- 导出格式全局统一（不做平台模板），target_platform 仅自由文本备注；
- 装配口径：当前剧本 + 出演角色（含选中立绘，未选中时取主立绘）+
  被选关键帧；快照生成后不受后续资产变更影响；
- 版本号按 (project_id, export_type) 递增。
"""

import json
import uuid

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
from utils.id import format_id

# 导出模板版本（统一格式，无平台差异）
EXPORT_TEMPLATE_VERSION = "unified-v1"

# 导出包名称长度上限（对齐 schema VARCHAR(200)）
_EXPORT_NAME_MAX = 200


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
                chosen = [art for art in arts if art.id in selected_art_ids] or [
                    art for art in arts if art.is_primary
                ]
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
            kf_ids = [row.asset_id for row in kf_sel_rows]
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
            keyframes_payload: list[dict] = []
            for row in kf_sel_rows:
                keyframe = keyframes_map.get(row.asset_id)
                if keyframe is None or keyframe.status == StoryKeyframeStatus.ARCHIVED:
                    continue
                kf_data = keyframe.to_dict()
                kf_data["characters"] = kfc_by_keyframe.get(keyframe.id, [])
                kf_data["sort_order"] = row.sort_order
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
        """把快照渲染为可直接复制到外部视频平台的统一文本。"""
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
