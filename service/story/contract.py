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
_ROLE_TYPES = {"protagonist", "supporting", "antagonist", "npc", "other", "scenery", "building", "landscape"}
_MAX_CARDS = 8

# 尾逗号（对象/数组最后一项后）；多逗号（`,,`）单独坍缩
_TRAILING_COMMA_RE = re.compile(r",+\s*([}\]])")
_DOUBLE_COMMA_RE = re.compile(r",\s*,+")


@dataclass
class DualTrack:
    """双轨解析结果：script_text 始终可用；cards 为角色卡列表；keyframes 为关键帧列表。"""

    script_text: str
    cards: list[dict] = field(default_factory=list)
    keyframes: list[dict] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    ok: bool = False
    error: str | None = None


_MAX_KEYFRAMES = 50

# 匹配类似: 【关键帧 1-1】[中景推近] [画面居中]【角色1·林冲】...（兼容旧版带 △ 前缀）
_SCRIPT_KEYFRAME_RE = re.compile(
    r"(?:△\s*)?【关键帧\s*(\d+)[-–—_](\d+)】\s*(?:（(?:预估\s*)?(\d+)\s*(?:秒|s|S)?）|\((?:预估\s*)?(\d+)\s*(?:秒|s|S)?\)|（[^）]+）|\([^)]+\))?\s*(?:\[([^\]]+)\])?\s*([^\n\r]+)",
    re.MULTILINE,
)


def _extract_keyframes_from_script(script_text: str) -> list[dict]:
    """从剧本正文中按【关键帧 场次-镜头】正则兜底提取关键帧（兼容 △ 前缀）。"""
    matches = _SCRIPT_KEYFRAME_RE.findall(script_text or "")
    results = []
    seen = set()
    for m in matches:
        try:
            scene_no = int(m[0])
            shot_no = int(m[1])
        except (ValueError, TypeError):
            continue
        key = (scene_no, shot_no)
        if key in seen:
            continue
        seen.add(key)
        duration_str = m[2] or m[3]
        try:
            duration_seconds = int(duration_str) if duration_str else None
        except (ValueError, TypeError):
            duration_seconds = None
        camera_desc = (m[4] or "").strip() or None
        raw_desc = (m[5] or "").strip()
        name = f"镜头 {scene_no}-{shot_no}"
        visual_desc = raw_desc or None
        prompt = f"{camera_desc}，{raw_desc}" if camera_desc else raw_desc
        results.append({
            "scene_no": scene_no,
            "shot_no": shot_no,
            "name": name,
            "duration_seconds": duration_seconds,
            "camera_description": camera_desc,
            "scene_description": raw_desc,
            "visual_description": visual_desc,
            "lighting_description": None,
            "style_description": None,
            "prompt": prompt or f"分镜镜头 {scene_no}-{shot_no}",
            "negative_prompt": None,
        })
    return results[:_MAX_KEYFRAMES]


def _normalize_keyframe(item) -> dict | None:
    """单关键帧规范化：scene_no/shot_no 转 int；prompt 保证有值。"""
    if not isinstance(item, dict):
        return None
    try:
        scene_no = int(item.get("scene_no")) if item.get("scene_no") is not None else 1
    except (ValueError, TypeError):
        scene_no = 1
    try:
        shot_no = int(item.get("shot_no")) if item.get("shot_no") is not None else 1
    except (ValueError, TypeError):
        shot_no = 1

    duration_val = item.get("duration_seconds") or item.get("duration")
    try:
        duration_seconds = int(duration_val) if duration_val is not None else None
    except (ValueError, TypeError):
        duration_seconds = None

    def _as_str(value) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    name = _as_str(item.get("name")) or f"镜头 {scene_no}-{shot_no}"
    camera_desc = _as_str(item.get("camera_description"))
    scene_desc = _as_str(item.get("scene_description"))
    visual_desc = _as_str(item.get("visual_description"))
    lighting_desc = _as_str(item.get("lighting_description"))
    style_desc = _as_str(item.get("style_description"))
    prompt = _as_str(item.get("prompt"))
    if not prompt:
        parts = [visual_desc, camera_desc, lighting_desc]
        prompt = "，".join(p for p in parts if p) or f"分镜镜头 {scene_no}-{shot_no}"
    negative_prompt = _as_str(item.get("negative_prompt"))

    return {
        "scene_no": scene_no,
        "shot_no": shot_no,
        "name": name,
        "duration_seconds": duration_seconds,
        "camera_description": camera_desc,
        "scene_description": scene_desc,
        "visual_description": visual_desc,
        "lighting_description": lighting_desc,
        "style_description": style_desc,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
    }


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


def classify_entity_type(
    name: str,
    appearance: str = "",
    profile: dict | None = None,
    visual_profile: dict | None = None,
    role_type: str | None = None,
) -> str:
    """分类实体类型：'character'(人物), 'building'(建筑/空间/地标), 'scenery'(风景/自然景观)。"""
    if role_type in ("building", "architecture"):
        return "building"
    if role_type in ("scenery", "landscape"):
        # 进一步按名称和细节微调是建筑空间还是自然风光
        text_check = f"{name} {appearance}"
        building_hints = (
            "城", "楼", "阁", "殿", "寺", "庙", "塔", "桥", "馆", "府", "院", "庄",
            "亭", "台", "轩", "榭", "宫", "房", "坞", "门", "寨", "站", "基地", "空间站",
            "穹顶", "大厦", "建筑", "街道", "街区", "地下街", "长廊", "遗迹", "舱室", "市集"
        )
        if any(h in text_check for h in building_hints):
            return "building"
        return "scenery"
    if role_type in ("protagonist", "supporting", "antagonist", "npc"):
        # 如果明确标注为人物类型，且名称不含明显非生物建筑/山水地貌，判定为人物
        non_human = ("城", "天空之城", "殿", "寺", "庙", "塔", "桥", "空间站", "古刹", "雪山", "星空", "残阳")
        if not any(h in name for h in non_human):
            return "character"

    text = f"{name} {appearance} {' '.join(str(v) for v in (profile or {}).values())} {' '.join(str(v) for v in (visual_profile or {}).values())}"

    building_keywords = (
        "城", "天空之城", "楼", "阁", "殿", "寺", "庙", "塔", "桥", "馆", "府", "院", "庄",
        "亭", "台", "轩", "榭", "宫", "房", "坞", "门", "寨", "站", "基地", "空间站", "穹顶",
        "大厦", "城堡", "宫殿", "古刹", "庭院", "建筑", "街道", "街区", "地下街", "广场", "遗迹",
        "渡口", "飞檐", "斗拱", "长廊", "舱室", "市集", "室内", "车厢"
    )
    landscape_keywords = (
        "湖", "山", "海", "江", "河", "溪", "瀑", "森林", "丛林", "树林", "林海", "竹林",
        "草原", "峡谷", "雪山", "雪原", "云海", "晨曦", "暮色", "残阳", "星河", "星空", "极光",
        "烟雨", "风景", "自然", "景观", "景致", "意境", "四季", "荒漠", "沙漠", "海岛", "原野",
        "水波", "断桥残雪", "雨景", "雪景", "雾气", "旷野"
    )
    person_keywords = (
        "主角", "配角", "反派", "少年", "少女", "男子", "女子", "青年", "老者", "老人", "将军",
        "侠客", "书生", "皇帝", "刺客", "警官", "侦探", "医生", "五官", "发型", "身材", "长相",
        "面容", "衣着", "服饰", "体态", "样貌", "神态", "眼神", "面部", "站姿", "肢体"
    )

    b_score = sum(1 for kw in building_keywords if kw in text)
    l_score = sum(1 for kw in landscape_keywords if kw in text)
    p_score = sum(1 for kw in person_keywords if kw in text)

    # 实体名具有极高权重
    if any(kw in name for kw in ("城", "天空之城", "楼", "阁", "殿", "寺", "塔", "桥", "大厦", "空间站", "宫", "街区")):
        b_score += 4
    if any(kw in name for kw in ("湖", "海", "江", "河", "雪原", "星空", "烟雨", "风景", "残阳", "晨曦")):
        l_score += 4

    if b_score > 0 and b_score >= p_score and b_score >= l_score:
        return "building"
    if l_score > 0 and l_score >= p_score and l_score > b_score:
        return "scenery"
    if role_type == "scenery":
        return "building" if b_score >= l_score else "scenery"
    return "character"


def build_entity_art_prompt(
    name: str,
    appearance: str = "",
    profile: dict | None = None,
    visual_profile: dict | None = None,
    role_type: str | None = None,
) -> tuple[str, str, str]:
    """根据实体类型（人物、建筑、风景）生成规范的 16:9 出图提示词与负向词，返回 (art_prompt, negative_prompt, role_type)。"""
    entity_type = classify_entity_type(name, appearance, profile, visual_profile, role_type)
    
    if entity_type == "building":
        assigned_role = role_type if role_type in ("building", "scenery") else "scenery"
        app_text = appearance or f"{name}空间规制与建筑材质细节"
        art_prompt = (
            f"16:9比例画面，影视级场景建筑概念美术设定图，多视角排版设计。"
            f"画面左侧为建筑主体全貌概念主视图，展现宏大空间轮廓、建筑规制、比例体量与环境气势；"
            f"画面右侧并列展示局部结构特写与材质纹理细节（如飞檐斗拱、雕花门窗、构件材质特写）。"
            f"同一建筑主体一致性。"
            f"建筑主体：{name}，{app_text}。"
            f"材质肌理清晰分明，真实物理自然采光与环境漫射光，空灵宏大空间氛围，照片级真实质感，电影级高清画质。"
            f"纯净空间，严禁出现任何人物，无人影，无面孔，无肢体，无服装，无插画卡通感，无3D建模塑料感 --ar 16:9"
        )
        negative_prompt = "人物，人影，面孔，肢体，服装，现代杂物，模糊失焦，低分辨率，插画感，二次元感，3D建模感，假皮塑料感，画面割裂，水印，字幕"
        return art_prompt, negative_prompt, assigned_role

    elif entity_type == "scenery":
        assigned_role = role_type if role_type in ("landscape", "scenery") else "scenery"
        app_text = appearance or f"{name}自然意境与光影流转细节"
        art_prompt = (
            f"16:9比例画面，超写实自然风景与意境概念设定图，多视角排版设计。"
            f"画面左侧为自然景观主体全貌概念主视图，展现宏大空间层次、山水地貌与天地意境氛围；"
            f"画面右侧并列展示微观自然细节特写（如水波倒影、植被岩石肌理、自然光影斑驳）。"
            f"同一自然景观一致性。"
            f"景观主体：{name}，{app_text}。"
            f"空气透视感强，真实自然光影与环境氛围，晨昏微光漫射，照片级真实质感，电影级高清画质。"
            f"纯自然空镜，严禁出现任何人物，无人影，无面孔，无肢体，无服装，无插画卡通感，无3D建模感 --ar 16:9"
        )
        negative_prompt = "人物，人影，面孔，肢体，服装，现代建筑，人工杂物，电线杆，模糊失焦，低分辨率，插画感，二次元感，3D建模感，塑料感，画面割裂，水印，字幕"
        return art_prompt, negative_prompt, assigned_role

    else:
        assigned_role = role_type or "supporting"
        app_text = appearance or f"{name}人物形象特写与全身站姿"
        art_prompt = (
            f"16:9比例画面，角色立绘四视图设计，左侧半身大头照正面特写为主视图（展示面部五官轮廓与神态细节），"
            f"右侧并列三张侧式图（全身正面、全身侧面、全身背面三视图，完整站立，从头到脚全身入镜）。"
            f"同一人物一致性（Same identity, facial consistency）。"
            f"人物主体：{name}，{app_text}。"
            f"服饰造型精致，材质质感清晰，电影级柔光摄影棚背景，侧逆光勾勒轮廓，照片级真实质感，电影级高清画质 --ar 16:9"
        )
        negative_prompt = "畸形肢体，多余手指，肢体残缺，模糊失焦，低分辨率，插画感，二次元感，3D建模感，假皮塑料感，多头，画面割裂"
        return art_prompt, negative_prompt, assigned_role


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

    profile = _as_dict(item.get("profile"))
    visual_profile = _as_dict(item.get("visual_profile"))
    appearance_prompt = _as_str(item.get("appearance_prompt"))
    art_prompt = _as_str(item.get("art_prompt"))
    negative_prompt = _as_str(item.get("negative_prompt"))

    # 如果缺少出图提示词，或提示词与建筑/风景类型错位（如建筑实体被套用了人物四视图），自动纠偏重构
    entity_type = classify_entity_type(name, appearance_prompt or "", profile, visual_profile, role_type)
    if entity_type in ("building", "scenery"):
        if not art_prompt or any(hp in art_prompt for hp in ("角色立绘四视图", "半身大头照", "五官轮廓", "全身正面、全身侧面、全身背面")):
            art_prompt, default_neg, inferred_role = build_entity_art_prompt(
                name, appearance_prompt or "", profile, visual_profile, role_type
            )
            negative_prompt = negative_prompt or default_neg
            if not role_type:
                role_type = inferred_role
    elif not art_prompt:
        art_prompt, default_neg, inferred_role = build_entity_art_prompt(
            name, appearance_prompt or "", profile, visual_profile, role_type
        )
        negative_prompt = negative_prompt or default_neg

    card = {"name": name, "role_type": role_type}
    card["profile"] = profile
    card["visual_profile"] = visual_profile
    card["appearance_prompt"] = appearance_prompt
    card["art_prompt"] = art_prompt
    card["negative_prompt"] = negative_prompt
    return card


def extract_characters_from_script(script_text: str) -> list[dict]:
    """从剧本正文（人物小传、角色介绍或场景建筑亮点）兜底提取结构化角色/景物卡。"""
    if not script_text:
        return []

    # 1. 尝试定位人物小传 / 角色介绍 或 纯景意境下的视觉亮点与空间设计段落
    bio_section = None
    patterns = [
        r"(?:##\s*|\b)[四4][、.\s]*人物小传[\s\S]*?(?=(?:##\s*|\b)[五5][、.\s]*剧本大纲|(?:##\s*|\b)[六6][、.\s]*剧本正文|\Z)",
        r"(?:##\s*|\b)(?:人物小传|主要角色|角色设定|角色列表|出演角色)[\s\S]*?(?=(?:##\s*|\b)(?:剧本大纲|分镜大纲|分镜头大纲|剧本正文|正文)|\Z)",
        r"(?:##\s*|\b)[四4][、.\s]*(?:视觉亮点与空间设计|场景与空间设计|景物与建筑设定|空间设计|景物设定)[\s\S]*?(?=(?:##\s*|\b)[五5][、.\s]*(?:场景变换大纲|剧本大纲|分镜大纲)|(?:##\s*|\b)[六6][、.\s]*分镜正文|\Z)",
        r"(?:##\s*|\b)(?:视觉亮点与空间设计|场景与空间设计|景物与建筑设定|场景建筑|空间设计|景物设定|核心景物|场景设定)[\s\S]*?(?=(?:##\s*|\b)(?:场景变换大纲|剧本大纲|分镜大纲|分镜正文|正文)|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, script_text)
        if m:
            bio_section = m.group(0)
            break

    search_text = bio_section if bio_section else script_text
    split_pat = r"\n(?=(?:\*{0,2}【(?:角色|景物|建筑)?\d*】|\*{0,2}【[^】\n]+】|###+\s*【?[^】\n]+】?|\d+[\.、]\s*【?[^】\n]+】?))"
    blocks = re.split(split_pat, search_text)

    characters: list[dict] = []
    seen_names: set[str] = set()

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if any(h in block for h in ("人物小传", "主要角色", "角色设定", "视觉亮点与空间设计", "场景变换大纲")) and len(block) < 30:
            continue

        first_line = block.split("\n")[0].strip("*# -")
        name = None
        m1 = re.search(r"【(?:角色|景物|建筑)?\d*】[·\s]*([^\s（(【】·]+)", first_line)
        if m1:
            name = m1.group(1).strip()
        else:
            m2 = re.search(r"【([^】]+)】", first_line)
            if m2:
                raw = m2.group(1).strip()
                if re.match(r"^(?:角色|景物|建筑)?\d+$", raw):
                    sub = re.search(r"(?:角色|景物|建筑)?\d+[·\s]+([^\s（(【】]+)", first_line)
                    if sub:
                        name = sub.group(1).strip()
                else:
                    name = re.sub(r"^(?:角色|景物|建筑)?\d+[·\s]*", "", raw).strip()
            else:
                m3 = re.search(r"^(?:\d+[\.、]\s*)?([^\s:：（(]+)", first_line)
                if m3:
                    cand = m3.group(1).strip()
                    if cand not in ("四", "人物小传", "角色", "主要角色", "一", "二", "三", "五", "六", "视觉亮点与空间设计"):
                        name = cand

        if not name or len(name) > 15:
            continue
        name = re.sub(r"[（(][^）)]*[）)]", "", name).strip("·:：*# ")
        if not name or name in seen_names or len(name) > 12:
            continue

        seen_names.add(name)
        lines = block.split("\n")[1:]
        profile: dict = {}
        visual_profile: dict = {}
        appearance_parts: list[str] = []

        for line in lines:
            line = line.strip("* -")
            if not line or line.startswith(("#", "四、", "一、", "二、", "三、", "五、", "六、")):
                continue
            if any(h in line for h in ("视觉亮点与空间设计", "空间设计", "场景设计", "人物小传")):
                continue
            if "：" in line or ":" in line:
                parts = re.split(r"[：:]", line, maxsplit=1)
                k = parts[0].strip()
                v = parts[1].strip() if len(parts) > 1 else ""
                if any(vk in k for vk in ("视觉", "外貌", "外观", "形象", "服饰", "体态", "样貌", "空间", "材质", "环境")):
                    visual_profile[k] = v
                    appearance_parts.append(v)
                else:
                    profile[k] = v
            elif any(vk in line for vk in ("视觉", "长相", "身材", "穿着", "面容", "空间", "材质", "建筑")):
                appearance_parts.append(line)

        appearance = "，".join(appearance_parts)
        idx = len(characters)
        default_role = "protagonist" if idx in (0, 1) else "supporting"
        if any(ant in str(profile.get("核心标签", "")) or ant in str(profile.get("身份背景", "")) for ant in ("反派", "敌对", "反角")):
            default_role = "antagonist"

        art_prompt, negative_prompt, role_type = build_entity_art_prompt(
            name=name,
            appearance=appearance,
            profile=profile,
            visual_profile=visual_profile,
            role_type=default_role,
        )

        characters.append({
            "name": name,
            "role_type": role_type,
            "profile": profile,
            "visual_profile": visual_profile,
            "appearance_prompt": appearance or f"{name}视觉特征描述",
            "art_prompt": art_prompt,
            "negative_prompt": negative_prompt,
        })

    # 若未能从小传解析出角色，尝试从出场人物或正文锚点提取
    if not characters:
        cast_match = re.search(r"出场人物[：:]\s*([^\n\r]+)", script_text)
        if cast_match:
            raw_cast = cast_match.group(1)
            for part in re.split(r"[,，、\s]+", raw_cast):
                m = re.search(r"(?:【角色\d+】|【)?([^\s（(【】·]+)", part)
                if m:
                    cand_name = m.group(1).strip("【】*· ")
                    cand_name = re.sub(r"[（(][^）)]*[）)]", "", cand_name).strip()
                    if cand_name and cand_name not in seen_names and len(cand_name) <= 10:
                        seen_names.add(cand_name)
                        art_prompt, neg_prompt, r_type = build_entity_art_prompt(
                            cand_name,
                            role_type="protagonist" if not characters else "supporting",
                        )
                        characters.append({
                            "name": cand_name,
                            "role_type": r_type,
                            "profile": {},
                            "visual_profile": {},
                            "appearance_prompt": f"{cand_name}形象特写与外观细节",
                            "art_prompt": art_prompt,
                            "negative_prompt": neg_prompt,
                        })

    if not characters:
        matches = re.findall(r"【(?:角色|景物|建筑)?\d*[·\s]+([^\s（(【】·]+)】", script_text)
        for cand_name in matches:
            cand_name = cand_name.strip("【】*· ")
            cand_name = re.sub(r"[（(][^）)]*[）)]", "", cand_name).strip()
            if cand_name and cand_name not in seen_names and len(cand_name) <= 10:
                seen_names.add(cand_name)
                art_prompt, neg_prompt, r_type = build_entity_art_prompt(
                    cand_name,
                    role_type="protagonist" if not characters else "supporting",
                )
                characters.append({
                    "name": cand_name,
                    "role_type": r_type,
                    "profile": {},
                    "visual_profile": {},
                    "appearance_prompt": f"{cand_name}形象特写与外观细节",
                    "art_prompt": art_prompt,
                    "negative_prompt": neg_prompt,
                })

    return characters[:_MAX_CARDS]


def split_dual_track(full_text: str) -> DualTrack:
    """剥离尾部角色卡与关键帧 JSON 块，返回双轨解析结果（永不抛异常）。"""
    full_text = full_text or ""
    begin_index = full_text.rfind(CARDS_BEGIN)
    if begin_index < 0:
        script_text = full_text.strip()
        keyframes = _extract_keyframes_from_script(script_text)
        cards = extract_characters_from_script(script_text)
        return DualTrack(
            script_text=script_text,
            cards=cards,
            keyframes=keyframes,
            ok=bool(cards or keyframes),
            error=None if (cards or keyframes) else "未找到结构化数据块",
        )
    script_text = full_text[:begin_index].rstrip()
    end_index = full_text.find(CARDS_END, begin_index + len(CARDS_BEGIN))
    raw = full_text[begin_index + len(CARDS_BEGIN) : end_index if end_index > 0 else None]
    payload = _loads_tolerant(raw)
    if not isinstance(payload, dict):
        keyframes = _extract_keyframes_from_script(script_text)
        cards = extract_characters_from_script(script_text)
        return DualTrack(
            script_text=script_text,
            cards=cards,
            keyframes=keyframes,
            ok=bool(cards or keyframes),
            error=None if (cards or keyframes) else "结构化数据块不是合法 JSON 对象",
        )
    cards: list[dict] = []
    raw_cards = payload.get("characters")
    if isinstance(raw_cards, dict):
        raw_cards = [raw_cards]
    if not isinstance(raw_cards, list):
        raw_cards = []
    for item in raw_cards[:_MAX_CARDS]:
        card = _normalize_card(item)
        if card is not None:
            cards.append(card)

    # 如果 JSON 中未产出角色卡，从剧本正文兜底提取
    if not cards:
        cards = extract_characters_from_script(script_text)

    raw_keyframes = payload.get("keyframes")
    keyframes: list[dict] = []
    if isinstance(raw_keyframes, dict):
        raw_keyframes = [raw_keyframes]
    if isinstance(raw_keyframes, list):
        for item in raw_keyframes[:_MAX_KEYFRAMES]:
            kf = _normalize_keyframe(item)
            if kf is not None:
                keyframes.append(kf)
    # 若 JSON 中未产出关键帧或为空，从剧本正文兜底提取
    if not keyframes:
        keyframes = _extract_keyframes_from_script(script_text)

    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    error = None if (cards or keyframes) else "角色卡与关键帧数组均为空"
    return DualTrack(
        script_text=script_text,
        cards=cards,
        keyframes=keyframes,
        params=params,
        ok=bool(cards or keyframes),
        error=error,
    )
