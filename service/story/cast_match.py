"""项目出演角色与剧本称呼匹配：关键帧导入/项目角色配置自动绑定出场角色。

名称绑定只发生在项目层：角色库角色 ↔ 当前剧本中的项目姓名（昵称）。
关键帧沉淀时按镜头文本与剧本关键帧行自动解析项目姓名，绑定角色库角色；
已有人工绑定的关键帧不覆盖。
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from database.story.character import CharacterArtRepository, CharacterRepository
from database.story.project import KeyframeCharacterRepository, ProjectAssetRepository

# 景物/建筑类资产不作为人物出场自动绑定
_NON_CHARACTER_ROLE_TYPES = frozenset({"scenery", "building", "landscape"})

# 【角色1·林冲】/【林冲】等角色引用标记
_CAST_BRACKET_RE = re.compile(r"【([^】]+)】")
_CAST_ROLE_PREFIX_RE = re.compile(r"^(?:角色|人物)\s*\d+\s*[·．.、\-–—_\s]*")
_CAST_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")

# 剧本正文中的关键帧行：【关键帧 1-2】...
_SCRIPT_KEYFRAME_LINE_RE = re.compile(
    r"【\s*关键帧\s*(\d+)\s*[-–—_]\s*(\d+)\s*】([^\n\r]*)"
)

_CAST_GENERIC_NAMES = frozenset(
    {"角色", "人物", "主角", "配角", "镜头", "关键帧", "画面", "场景", "背景", "前景"}
)


def _clean_cast_marker(raw: str) -> str:
    """清洗【...】内容：去掉角色编号前缀与括号补充。"""
    text = _CAST_ROLE_PREFIX_RE.sub("", raw.strip())
    text = _CAST_PAREN_RE.sub("", text)
    return text.strip(" ·:：,，;；[]【】")


def script_keyframe_lines(content: str | None) -> dict[tuple[int, int], str]:
    """解析剧本正文关键帧行，返回 {(scene_no, shot_no): 行文本}。"""
    if not content:
        return {}
    lines: dict[tuple[int, int], str] = {}
    for match in _SCRIPT_KEYFRAME_LINE_RE.finditer(content):
        key = (int(match.group(1)), int(match.group(2)))
        lines.setdefault(key, match.group(3).strip())
    return lines


def match_cast_bindings(bindings: list[dict], text: str) -> list[dict]:
    """按【角色编号·名称】标记与纯文本名称匹配出演角色，按出现顺序返回。"""
    if not bindings or not text:
        return []

    matched: dict[uuid.UUID, tuple[int, dict]] = {}
    markers: list[tuple[int, str, str]] = []
    for match in _CAST_BRACKET_RE.finditer(text):
        raw = match.group(1).strip()
        cleaned = _clean_cast_marker(raw)
        if cleaned and not cleaned.startswith("关键帧"):
            markers.append((match.start(), raw, cleaned))

    # 优先匹配显式角色标记，避免正文普通词误伤
    for binding in bindings:
        for position, raw, cleaned in markers:
            if any(alias in (raw, cleaned) for alias in binding["aliases"]):
                current = matched.get(binding["character_id"])
                if current is None or position < current[0]:
                    matched[binding["character_id"]] = (position, binding)
                break

    matched_aliases = {
        alias for _, binding in matched.values() for alias in binding["aliases"]
    }
    # 标记未覆盖的角色再用纯文本补充；长名优先，跳过已被长名包含的短名
    for binding in bindings:
        if binding["character_id"] in matched:
            continue
        for alias in sorted(binding["aliases"], key=len, reverse=True):
            if len(alias) < 2 or alias in _CAST_GENERIC_NAMES:
                continue
            if any(alias != other and alias in other for other in matched_aliases):
                continue
            position = text.find(alias)
            if position >= 0:
                matched[binding["character_id"]] = (position, binding)
                matched_aliases.add(alias)
                break

    return [
        binding for _, binding in sorted(matched.values(), key=lambda item: item[0])
    ]


async def load_cast_bindings(
    session: AsyncSession, project_id: uuid.UUID
) -> list[dict]:
    """加载项目人物出演角色及其项目姓名/默认参考立绘。"""
    asset_repo = ProjectAssetRepository(session)
    rows = await asset_repo.list_by_type(project_id, "character")
    if not rows:
        return []
    character_ids = {row.asset_id for row in rows}
    characters = await CharacterRepository(session).get_many(character_ids)
    arts_by_char = await CharacterArtRepository(session).list_by_characters(
        character_ids
    )
    selected_art_ids = {
        row.asset_id
        for row in await asset_repo.list_by_type(project_id, "character_art")
    }

    bindings: list[dict] = []
    alias_owners: dict[str, set[uuid.UUID]] = {}
    for row in rows:
        character = characters.get(row.asset_id)
        if character is None:
            continue
        if (character.role_type or "") in _NON_CHARACTER_ROLE_TYPES:
            continue
        aliases: list[str] = []
        for candidate in (row.script_name, character.name):
            alias = (candidate or "").strip()
            if alias and alias not in aliases:
                aliases.append(alias)
        if not aliases:
            continue

        arts = arts_by_char.get(character.id, [])
        chosen_art = next((art for art in arts if art.id in selected_art_ids), None)
        if chosen_art is None:
            chosen_art = next((art for art in arts if art.is_primary), None)
        if chosen_art is None and arts:
            chosen_art = arts[0]

        bindings.append(
            {
                "character_id": character.id,
                "aliases": aliases,
                "character_art_id": chosen_art.id if chosen_art else None,
            }
        )
        for alias in aliases:
            alias_owners.setdefault(alias, set()).add(character.id)

    # 同一称呼对应多个角色时视为歧义，剔除该称呼避免误绑
    ambiguous = {alias for alias, owners in alias_owners.items() if len(owners) > 1}
    if ambiguous:
        for binding in bindings:
            binding["aliases"] = [
                alias for alias in binding["aliases"] if alias not in ambiguous
            ]
    return [binding for binding in bindings if binding["aliases"]]


async def auto_bind_keyframe_characters(
    session: AsyncSession,
    keyframe_id: uuid.UUID,
    texts: list[str | None],
    scene_no: int | None,
    shot_no: int | None,
    bindings: list[dict],
    script_lines: dict[tuple[int, int], str],
) -> int:
    """为无出场角色的关键帧按镜头文本自动绑定人物，返回新增绑定数。"""
    if not bindings:
        return 0
    kfc_repo = KeyframeCharacterRepository(session)
    if await kfc_repo.list_by_keyframe(keyframe_id):
        return 0

    parts = [text.strip() for text in texts if text and text.strip()]
    if scene_no is not None and shot_no is not None:
        script_line = script_lines.get((int(scene_no), int(shot_no)))
        if script_line:
            parts.append(script_line)
    if not parts:
        return 0

    matched = match_cast_bindings(bindings, "\n".join(parts))
    if not matched:
        return 0
    await kfc_repo.replace_for_keyframe(
        keyframe_id,
        [
            {
                "character_id": binding["character_id"],
                "character_art_id": binding["character_art_id"],
                "role": None,
                "character_prompt": None,
            }
            for binding in matched
        ],
    )
    return len(matched)
