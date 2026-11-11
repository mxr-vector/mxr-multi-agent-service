"""
剧本模块视频片段编排：把当前剧本按章节组合成「一份剧本 + 一组关键帧」的生成单元。

- 章节识别：`第1集` / `第1章` / `第1幕` 标题（支持 Markdown 标题前缀与
  “第1集：标题（预估生成时长：xx秒）”写法）；
- 镜头识别：分镜正文中的 `【关键帧 场次-镜头】` 标记；标记到下一个标记
  之间的文本即该镜头的剧本文本；
- 自动编排：优先使用关键帧显式 chapter_no，其次按（场次, 镜头）匹配剧本
  标记；章节内按标记顺序生成 blocks（正文文本 + 对应关键帧图片），并把
  标记替换为【图k】合成一份整章提示词，供用户确认/编辑后一次生成一个片段；
- 无法匹配章节/标记的关键帧进入「未匹配章节的镜头」，仍可按一组生成。
"""

import re
import uuid

from agent.constants.enums.story import StoryKeyframeStatus
from database.postgre_client import get_session
from database.story.character import CharacterRepository
from database.story.project import (
    KeyframeCharacterRepository,
    KeyframeRepository,
    ScriptRepository,
)
from service.story.project import ProjectService

# 整章提示词上限：章节正文 + 所有参考图描述，允许用户在前端继续精简
PROMPT_MAX_CHARS = 4000

# 章节标题：允许 ### 前缀、第1集/章/幕、可选标题与时长备注
_CHAPTER_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*+]\s*)?第\s*(\d+)\s*[集章幕]\s*"
    r"(?:[：:、\-—–]\s*)?(.*)$"
)

# 关键帧标记：兼容 `【关键帧 1-1】` / `【关键帧 场次1-镜头1】`
_KEYFRAME_RE = re.compile(
    r"【\s*关键帧\s*(?:场次)?\s*(\d+)\s*[-－—–]\s*(?:镜头)?\s*(\d+)\s*】"
)

# 标题/镜头文本中的预估时长备注（不进入生成提示词）
_DURATION_RE = re.compile(r"[（(][^）)]*(?:预估|时长)[^）)]*[）)]")


def _clean_title(raw: str, chapter_no: int) -> str:
    """清洗章节标题：去时长备注与分隔符；无标题时回落“第N集”。"""
    title = _DURATION_RE.sub("", raw or "").strip().strip("：:、-—– ")
    return title or f"第{chapter_no}集"


def _clean_shot_text(raw: str) -> str:
    """清洗镜头文本：去时长备注与开头分隔符。"""
    text = _DURATION_RE.sub("", raw or "").strip()
    return text.strip("：:、-—– ")


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _keyframe_label(keyframe) -> str:
    if keyframe.name and keyframe.name.strip():
        return keyframe.name.strip()
    if keyframe.scene_no is not None and keyframe.shot_no is not None:
        return f"场景{keyframe.scene_no}-镜头{keyframe.shot_no}"
    return keyframe.id.hex


def parse_script_chapters(content: str) -> list[dict]:
    """把剧本解析为章节列表，并提取每章的关键帧标记、位置与镜头文本。"""
    raw_chapters: list[dict] = []
    current: dict | None = None
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        match = _CHAPTER_RE.match(line)
        if match:
            chapter_no = int(match.group(1))
            current = {
                "chapter_no": chapter_no,
                "title": _clean_title(match.group(2), chapter_no),
                "lines": [],
            }
            raw_chapters.append(current)
            continue
        if current is not None:
            current["lines"].append(raw_line)

    if not raw_chapters:
        return []

    chapters: list[dict] = []
    for raw in raw_chapters:
        body = "\n".join(raw["lines"]).strip()
        markers = list(_KEYFRAME_RE.finditer(body))
        shot_markers: list[dict] = []
        for index, marker in enumerate(markers):
            start = marker.end()
            end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
            shot_markers.append(
                {
                    "scene_no": int(marker.group(1)),
                    "shot_no": int(marker.group(2)),
                    "content": _clean_shot_text(body[start:end]),
                    "order": index,
                    "start": marker.start(),
                    "end": marker.end(),
                }
            )
        context = body[: markers[0].start()].strip() if markers else body.strip()
        chapters.append(
            {
                "chapter_no": raw["chapter_no"],
                "title": raw["title"],
                "content": body,
                "context": context,
                "markers": shot_markers,
            }
        )
    return chapters


def _shot_detail(keyframe, character_names: list[str] | None = None) -> str:
    """关键帧的画面描述（用于参考图说明与提示词补强）。"""
    parts: list[str] = []
    if keyframe.prompt and keyframe.prompt.strip():
        parts.append(f"画面：{keyframe.prompt.strip()}")
    if character_names:
        parts.append(f"出场角色：{'、'.join(character_names)}")
    return "\n".join(parts)


def _clean_block_text(text: str) -> str:
    """清理编排文本中的预估时长、标记符号与空行。"""
    cleaned = _DURATION_RE.sub("", text or "")
    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = re.sub(r"^\s*[△▲]\s*", "", raw_line).rstrip()
        if not line.strip():
            continue
        # 集/镜头预估时长行不进入生成提示词（时长由用户规格决定）
        if _DURATION_RE.fullmatch(line.strip()) or line.strip().startswith(
            ("预估时长", "预估生成时长")
        ):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _image_block(keyframe, index: int) -> dict:
    label = f"图{index}" if index > 0 else "缺图"
    return {
        "type": "image",
        "keyframe_id": keyframe.id.hex,
        "image_file": keyframe.image_file,
        "has_image": bool(keyframe.image_file),
        "label": f"{label} · {_keyframe_label(keyframe)}",
        "name": _keyframe_label(keyframe),
        "scene_no": keyframe.scene_no,
        "shot_no": keyframe.shot_no,
    }


def _replace_markers(content: str, replacements: list[tuple[dict, int]]) -> str:
    """把已匹配的关键帧标记替换为【图k】/【缺图】，保留未匹配标记原文。"""
    marked = content
    for marker, index in sorted(
        replacements, key=lambda item: item[0]["start"], reverse=True
    ):
        label = f"图{index}" if index > 0 else "缺图"
        marked = (
            marked[: marker["start"]]
            + f"【{label}】"
            + marked[marker["end"] :]
        )
    return marked


def _chapter_blocks(
    content: str,
    markers: list[dict],
    matched: dict[tuple[int, int], tuple[int, object]],
) -> list[dict]:
    """按剧本顺序生成文本/图片块：图片落在关键帧标记的位置。"""
    blocks: list[dict] = []
    cursor = 0
    for marker in markers:
        key = (marker["scene_no"], marker["shot_no"])
        hit = matched.get(key)
        if hit is None:
            continue
        index, keyframe = hit
        if marker["start"] > cursor:
            text = _clean_block_text(content[cursor : marker["start"]])
            if text:
                blocks.append({"type": "text", "text": text})
        blocks.append(_image_block(keyframe, index))
        cursor = marker["end"]
    tail = _clean_block_text(content[cursor:])
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks


class VideoPlanService:
    """章节级视频编排：项目属主校验 + 剧本/关键帧对齐 + 整章提示词。"""

    def __init__(self) -> None:
        self._project_service = ProjectService()

    async def plan(self, ctx, project_id: uuid.UUID) -> dict:
        """返回按章节组织的生成单元（正文块、图片位置、整章提示词）。"""
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            script = await ScriptRepository(session).get_current(project_id)
            keyframes, _ = await KeyframeRepository(session).list_by_project(
                project_id, page=1, size=10_000
            )
            keyframes = [
                keyframe
                for keyframe in keyframes
                if keyframe.status != StoryKeyframeStatus.ARCHIVED.value
            ]
            # 只编排当前剧本版本或未绑定版本的镜头，避免旧版本残留镜头重复出现
            if script is not None:
                keyframes = [
                    keyframe
                    for keyframe in keyframes
                    if keyframe.script_id in (None, script.id)
                ]
            character_names = await self._character_names(session, keyframes)
            parsed = parse_script_chapters(script.content) if script else []

        chapters = self._compose(parsed, keyframes, character_names)
        return {
            "script": (
                {
                    "id": script.id.hex,
                    "version": script.version,
                    "title": script.title,
                    "is_current": script.is_current,
                }
                if script
                else None
            ),
            "chapters": chapters,
        }

    def _compose(self, parsed: list[dict], keyframes: list, names: dict) -> list[dict]:
        """把章节定义与关键帧合并为生成单元，按剧本顺序输出。"""
        groups: dict[int | None, dict] = {}
        for chapter in parsed:
            groups[chapter["chapter_no"]] = {
                "chapter_no": chapter["chapter_no"],
                "title": chapter["title"],
                "content": chapter["content"],
                "context": chapter["context"],
                "markers": chapter["markers"],
                "items": [],
                "unmatched": False,
            }
        if not parsed:
            chapter_numbers = sorted(
                {
                    keyframe.chapter_no
                    for keyframe in keyframes
                    if keyframe.chapter_no is not None
                }
            )
            for chapter_no in chapter_numbers:
                groups[chapter_no] = {
                    "chapter_no": chapter_no,
                    "title": f"第{chapter_no}集",
                    "content": "",
                    "context": "",
                    "markers": [],
                    "items": [],
                    "unmatched": False,
                }
            if not chapter_numbers or any(
                keyframe.chapter_no is None for keyframe in keyframes
            ):
                groups[None] = {
                    "chapter_no": None,
                    "title": "全部镜头",
                    "content": "",
                    "context": "",
                    "markers": [],
                    "items": [],
                    "unmatched": False,
                }
        else:
            for keyframe in keyframes:
                chapter_no = keyframe.chapter_no
                if chapter_no is not None and chapter_no not in groups:
                    groups[chapter_no] = {
                        "chapter_no": chapter_no,
                        "title": f"第{chapter_no}集",
                        "content": "",
                        "context": "",
                        "markers": [],
                        "items": [],
                        "unmatched": False,
                    }

        marker_map: dict[tuple[int, int], dict] = {}
        for chapter in parsed:
            for marker in chapter["markers"]:
                marker_map[(marker["scene_no"], marker["shot_no"])] = {
                    **marker,
                    "chapter_no": chapter["chapter_no"],
                }

        unmatched_items: list[tuple] = []
        for keyframe in keyframes:
            pair = (keyframe.scene_no, keyframe.shot_no)
            marker = marker_map.get(pair)
            chapter_no: int | None = None
            if keyframe.chapter_no is not None and keyframe.chapter_no in groups:
                chapter_no = keyframe.chapter_no
            elif marker is not None and marker["chapter_no"] in groups:
                chapter_no = marker["chapter_no"]
            elif None in groups:
                chapter_no = None

            if chapter_no is None and None not in groups:
                unmatched_items.append((None, keyframe, "", None))
                continue

            shot_content = ""
            matched_marker = None
            if marker is not None and marker["chapter_no"] == chapter_no:
                shot_content = marker["content"]
                matched_marker = marker
            groups[chapter_no]["items"].append(
                (
                    matched_marker["order"] if matched_marker else None,
                    keyframe,
                    shot_content,
                    matched_marker,
                )
            )

        chapters: list[dict] = []
        for group in groups.values():
            items = sorted(group["items"], key=self._shot_sort_key)
            if not items:
                continue
            chapters.append(
                self._build_chapter(
                    group["chapter_no"],
                    group["title"],
                    group["content"],
                    group["markers"],
                    items,
                    names,
                    unmatched=False,
                )
            )

        if unmatched_items:
            items = sorted(unmatched_items, key=self._shot_sort_key)
            chapters.append(
                self._build_chapter(
                    None,
                    "未匹配章节的镜头",
                    "",
                    [],
                    items,
                    names,
                    unmatched=True,
                )
            )

        chapters.sort(
            key=lambda item: (
                bool(item["unmatched"]),
                item["chapter_no"] is None,
                item["chapter_no"] or 0,
            )
        )
        return chapters

    @staticmethod
    def _shot_sort_key(item: tuple) -> tuple:
        order, keyframe, _, _ = item
        return (
            order if order is not None else 10**6,
            keyframe.scene_no if keyframe.scene_no is not None else 10**9,
            keyframe.shot_no if keyframe.shot_no is not None else 10**9,
            keyframe.created_at,
        )

    def _build_chapter(
        self,
        chapter_no: int | None,
        title: str,
        content: str,
        markers: list[dict],
        items: list[tuple],
        names: dict,
        *,
        unmatched: bool,
    ) -> dict:
        """组装单章：图片位置块、参考图清单与整章提示词。"""
        # 只有已出图的关键帧参与参考图编号；缺图镜头保留占位但不占图号
        image_index: dict[uuid.UUID, int] = {}
        for _, keyframe, _, _ in items:
            if keyframe.image_file:
                image_index[keyframe.id] = len(image_index) + 1
        keyframe_ids = [
            keyframe.id.hex
            for _, keyframe, _, _ in items
            if keyframe.id in image_index
        ]

        matched: dict[tuple[int, int], tuple[int, object]] = {}
        replacements: list[tuple[dict, int]] = []
        for _, keyframe, _, marker in items:
            if marker is None:
                continue
            index = image_index.get(keyframe.id, 0)
            matched[(marker["scene_no"], marker["shot_no"])] = (index, keyframe)
            replacements.append((marker, index))

        if content and markers:
            blocks = _chapter_blocks(content, markers, matched)
        else:
            blocks = []

        # 未落在剧本标记位置的关键帧追加到章节末尾
        attached_ids = {
            keyframe.id for (_, keyframe, _, marker) in items if marker is not None
        }
        for _, keyframe, shot_content, _ in items:
            if keyframe.id in attached_ids:
                continue
            blocks.append(
                _image_block(keyframe, image_index.get(keyframe.id, 0))
            )
            detail = shot_content or _shot_detail(keyframe, names.get(keyframe.id, []))
            if detail:
                blocks.append({"type": "text", "text": detail})

        prompt_parts = [f"章节：{title}"]
        if content:
            prompt_parts.append(
                "剧本正文（图k为对应关键帧参考图）：\n"
                + _clean_block_text(_replace_markers(content, replacements))
            )
        reference_lines: list[str] = []
        for _, keyframe, shot_content, _ in items:
            index = image_index.get(keyframe.id)
            if index is None:
                continue
            detail = _shot_detail(keyframe, names.get(keyframe.id, []))
            text = (shot_content or "").strip()
            body = f"{text}\n{detail}" if text else detail
            reference_lines.append(
                f"图{index}（{_keyframe_label(keyframe)}）：{body or '按参考图保持画面一致'}"
            )
        if reference_lines:
            prompt_parts.append(
                "画面参考（按图序生成）：\n" + "\n".join(reference_lines)
            )
        prompt_parts.append(
            "请按剧本顺序与参考图生成一个连贯的视频片段，保持人物形象与场景一致，"
            "动作自然连贯，镜头运动符合上述描述。"
        )

        return {
            "chapter_no": chapter_no,
            "title": title,
            "content": content,
            "blocks": blocks,
            "prompt": _truncate("\n\n".join(prompt_parts), PROMPT_MAX_CHARS),
            "keyframe_ids": keyframe_ids,
            "shots": [
                {
                    "keyframe_id": keyframe.id.hex,
                    "scene_no": keyframe.scene_no,
                    "shot_no": keyframe.shot_no,
                    "name": _keyframe_label(keyframe),
                    "image_file": keyframe.image_file,
                    "has_image": bool(keyframe.image_file),
                    "shot_content": shot_content,
                }
                for _, keyframe, shot_content, _ in items
            ],
            "unmatched": unmatched,
        }

    async def _character_names(self, session, keyframes: list) -> dict:
        """批量取关键帧出场角色名（提示词补充用，避免 N+1）。"""
        keyframe_ids = [keyframe.id for keyframe in keyframes]
        if not keyframe_ids:
            return {}
        rows = await KeyframeCharacterRepository(session).list_by_keyframes(
            keyframe_ids
        )
        character_ids = {row.character_id for row in rows}
        characters = (
            await CharacterRepository(session).get_many(character_ids)
            if character_ids
            else {}
        )
        grouped: dict[uuid.UUID, list[str]] = {
            keyframe_id: [] for keyframe_id in keyframe_ids
        }
        for row in rows:
            character = characters.get(row.character_id)
            if character and character.name not in grouped[row.keyframe_id]:
                grouped[row.keyframe_id].append(character.name)
        return grouped
