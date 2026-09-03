"""
agent/skills 技能包只读 loader 与剧本生成风格注册表（story-ai-workspace）。

技能包（agent/skills/<name>/SKILL.md + references/）是静态知识资产：
本模块只读加载并按节裁剪注入生成提示词，绝不执行技能包内脚本。

风格注册表把"用户可见的视频风格"绑定到技能知识源与画幅预设：
- generic       → seedance-storyboard-generator（通用短剧，风格开放）
- shangmeiying  → smy-seedance-storyboard-main（上美影动画，风格锁定）
- handdrawn     → story-handdrawn-remotion-main（手绘日记）
story-handdrawn-video-main 与 remotion 版同属手绘家族且为脚本链路变体，
不单独暴露（并入手绘日记知识源）。

注入策略：SKILL.md 全文过长（500+ 行），按"前言 + 命中标题的整节"裁剪——
各风格声明必选节关键词（叙事格式/风格块与色盘/人物小传与资产提示词），
未命中关键词的节（质量自检清单等）不进提示词。
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from exception.bad_except import bad_except
from utils.logger import logger

# 技能包根目录（agent/skills/）
SKILLS_ROOT = Path(__file__).resolve().parent

# 各风格注入 SKILL.md 时命中的标题关键词（标题含任一关键词即整节注入）
_DEFAULT_SECTIONS = ("剧本", "资产")
_STYLE_SECTIONS: dict[str, tuple[str, ...]] = {
    # 通用短剧：剧本格式 + 资产提示词规则
    "generic": _DEFAULT_SECTIONS,
    # 上美影：风格声明（前言自带）+ 制作参数（色盘声明）+ 剧本 + 资产
    "shangmeiying": ("风格声明", "制作参数", *_DEFAULT_SECTIONS),
    # 手绘日记：一句一拍叙事 + 风格 DNA（五色限定/墨色轮廓/安全边距）
    # + 场景语法版式约定 + 视觉规划（无传统剧本节，前言承担风格描述）
    "handdrawn": ("风格 DNA", "场景语法", "视觉规划", "写 story", "故事忠实度"),
}


@dataclass(frozen=True)
class StyleEntry:
    """注册表条目：风格 key → 技能知识源 + 画幅预设 + 注入节关键词。"""

    key: str
    name: str
    description: str
    skill_dir: str
    aspect_ratios: tuple[str, ...]
    section_keywords: tuple[str, ...] = field(default=())


STYLE_REGISTRY: dict[str, StyleEntry] = {
    entry.key: entry
    for entry in (
        StyleEntry(
            key="generic",
            name="通用短剧",
            description="Seedance 分镜工作流，风格开放（写实/动画/水墨/科幻等），"
            "△剧本+人物小传+资产出图提示词",
            skill_dir="seedance-storyboard-generator",
            aspect_ratios=("16:9", "9:16", "4:3"),
            section_keywords=_STYLE_SECTIONS["generic"],
        ),
        StyleEntry(
            key="shangmeiying",
            name="上美影动画",
            description="上美影复古手绘动画风格（水墨线条/矿物颜料平涂），"
            "剧组色盘声明，国风短剧专用",
            skill_dir="smy-seedance-storyboard-main",
            aspect_ratios=("9:16", "16:9", "4:3"),
            section_keywords=_STYLE_SECTIONS["shangmeiying"],
        ),
        StyleEntry(
            key="handdrawn",
            name="手绘日记",
            description="手绘日记漫画风（白底+记号笔轮廓+蜡笔色），一句一拍"
            "竖屏叙事，适合生活叙事/绘本/教学小品",
            skill_dir="story-handdrawn-remotion-main",
            aspect_ratios=("3:4", "9:16"),
            section_keywords=_STYLE_SECTIONS["handdrawn"],
        ),
    )
}


def get_style(style_key: str) -> StyleEntry:
    """按 key 取注册表条目；未注册风格明确拒绝（不发起模型调用）。"""
    entry = STYLE_REGISTRY.get(style_key)
    if entry is None:
        known = ", ".join(sorted(STYLE_REGISTRY))
        bad_except(f"未注册的视频风格: {style_key}（可选：{known}）")
    return entry


def list_styles() -> list[dict]:
    """枚举风格列表（前端生成表单数据源）。"""
    return [
        {
            "key": entry.key,
            "name": entry.name,
            "description": entry.description,
            "aspect_ratios": list(entry.aspect_ratios),
        }
        for entry in STYLE_REGISTRY.values()
    ]


@lru_cache(maxsize=8)
def _read_skill_file(skill_dir: str, filename: str) -> str:
    """读取技能包内文本文件（只读缓存）；缺失告警并返回空串。

    缺失静默返回空串会让部署漏拷技能包时表现为无日志的产出质量漂移，
    故显式告警（不 fail-fast：技能缺失不应阻断已有功能的其余链路）。
    """
    path = SKILLS_ROOT / skill_dir / filename
    if not path.is_file():
        logger.warning(f"[SKILL] 技能包文件缺失: {path}（检查部署是否漏拷 agent/skills）")
        return ""
    return path.read_text(encoding="utf-8")


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*```")


@lru_cache(maxsize=8)
def _split_sections(text: str) -> "list[tuple[str, str]]":
    """把 markdown 拆为（标题, 节全文）列表；首个标题前的前言标题为空串。

    代码围栏（```）内的 `# ` 行是注释而非标题，须跳过以免误切段边界。
    """
    sections: "list[tuple[str, str]]" = []
    current_title = ""
    lines: "list[str]" = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            lines.append(line)
            continue
        if not in_fence:
            match = _HEADING_RE.match(line)
            if match:
                sections.append((current_title, "\n".join(lines)))
                current_title = match.group(2).strip()
                lines = [line]
                continue
        lines.append(line)
    sections.append((current_title, "\n".join(lines)))
    return sections


@lru_cache(maxsize=8)
def load_skill_excerpt(skill_dir: str, keywords: tuple[str, ...]) -> str:
    """加载技能 SKILL.md 并按关键词裁剪：前言 + 标题命中关键词的整节。

    命中节保留其全部子节（叙事格式规范是连贯整体，不做更深切分）。
    """
    text = _read_skill_file(skill_dir, "SKILL.md")
    if not text:
        return ""
    parts: list[str] = []
    for title, body in _split_sections(text):
        if not title:
            # 前言（含 frontmatter 之后的风格总述）始终注入
            parts.append(body)
        elif any(keyword in title for keyword in keywords):
            parts.append(body)
    excerpt = "\n\n".join(part for part in parts if part.strip())
    if not excerpt:
        bad_except(f"技能 {skill_dir} 未命中任何注入节（keywords={keywords}）")
    return excerpt
