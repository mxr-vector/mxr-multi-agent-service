"""
双轨输出契约解析（story-ai-workspace）。

从模型流式全文中剥离尾部角色卡 JSON 块（D4）：
- 剧本文本 = 起始标记之前的全部内容；
- 角色卡/参数 = 标记之间 JSON，容错 ```json 围栏、尾逗号、标记缺失；
- 解析失败降级为纯剧本（cards 空 + ok=False），不抛异常——由调用方决定
  落库与提示策略（spec"结构化缺失降级"场景）。
"""

import json
import re
from dataclasses import dataclass, field

# 契约标记（与 agent/prompts/story.py 的输出契约保持一致）
CARDS_BEGIN = "<<<STORY_CARDS>>>"
CARDS_END = "<<<END_STORY_CARDS>>>"

# 卡片字段白名单与角色类型取值域
_CARD_FIELDS = ("name", "role_type", "profile", "visual_profile", "appearance_prompt", "art_prompt", "negative_prompt")
_ROLE_TYPES = {"protagonist", "supporting", "antagonist", "npc", "other"}
_MAX_CARDS = 8

# 尾逗号（对象/数组最后一项后）；多逗号（`,,`）单独坍缩
_TRAILING_COMMA_RE = re.compile(r",+\s*([}\]])")
_DOUBLE_COMMA_RE = re.compile(r",\s*,+")


@dataclass
class DualTrack:
    """双轨解析结果：script_text 始终可用；cards 为规范化角色卡列表。"""

    script_text: str
    cards: list[dict] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    ok: bool = False
    error: str | None = None


def _loads_tolerant(raw: str):
    """容错 JSON 解析：剥围栏 -> 直接解析 -> 去尾逗号后解析 -> 提取最外层大括号。"""
    raw = raw.strip()
    # ```json 围栏（模型不守约时兜底）
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", raw)
    if fence:
        raw = fence.group(1).strip()
    candidates = [raw]
    variants = [
        _TRAILING_COMMA_RE.sub(r"\1", raw),
        _DOUBLE_COMMA_RE.sub(",", raw),
    ]
    variants.append(_TRAILING_COMMA_RE.sub(r"\1", variants[-1]))
    candidates.extend(variants)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    # 裸 JSON（标记内混入说明文字时提取首个大括号块）
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        snippet = raw[start : end + 1]
        for candidate in (
            snippet,
            _TRAILING_COMMA_RE.sub(r"\1", snippet),
            _TRAILING_COMMA_RE.sub(r"\1", _DOUBLE_COMMA_RE.sub(",", snippet)),
        ):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None


def _normalize_card(item) -> dict | None:
    """单卡规范化：name 必填非空；dict 字段收敛为 dict、文本字段收敛为 str。"""
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    role_type = item.get("role_type")
    role_type = str(role_type).strip() if role_type else None
    if role_type not in _ROLE_TYPES:
        role_type = None

    def _as_dict(value) -> dict:
        return dict(value) if isinstance(value, dict) else {}

    def _as_str(value) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    card = {"name": name, "role_type": role_type}
    card["profile"] = _as_dict(item.get("profile"))
    card["visual_profile"] = _as_dict(item.get("visual_profile"))
    card["appearance_prompt"] = _as_str(item.get("appearance_prompt"))
    card["art_prompt"] = _as_str(item.get("art_prompt"))
    card["negative_prompt"] = _as_str(item.get("negative_prompt"))
    return card


def split_dual_track(full_text: str) -> DualTrack:
    """剥离尾部角色卡 JSON 块，返回双轨解析结果（永不抛异常）。"""
    full_text = full_text or ""
    begin_index = full_text.rfind(CARDS_BEGIN)
    if begin_index < 0:
        return DualTrack(script_text=full_text.strip(), error="未找到角色卡数据块")
    script_text = full_text[:begin_index].rstrip()
    end_index = full_text.find(CARDS_END, begin_index + len(CARDS_BEGIN))
    raw = full_text[begin_index + len(CARDS_BEGIN) : end_index if end_index > 0 else None]
    payload = _loads_tolerant(raw)
    if not isinstance(payload, dict):
        return DualTrack(
            script_text=script_text,
            error="角色卡数据块不是合法 JSON 对象",
        )
    cards: list[dict] = []
    # characters 容错收敛：模型偶发输出单对象/非数组（如 {"name": ...} 或数字），
    # 切片直接抛异常会击穿"永不抛异常"契约，把已完成剧本误判为 failed（D4）
    raw_cards = payload.get("characters")
    if isinstance(raw_cards, dict):
        raw_cards = [raw_cards]
    if not isinstance(raw_cards, list):
        raw_cards = []
    for item in raw_cards[:_MAX_CARDS]:
        card = _normalize_card(item)
        if card is not None:
            cards.append(card)
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    error = None if cards else "角色卡数组为空或全部无效"
    return DualTrack(script_text=script_text, cards=cards, params=params, ok=bool(cards), error=error)
