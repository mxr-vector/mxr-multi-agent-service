"""gen_story_images.py — 故事文本 → apiz 生成 master → ffmpeg 切三层 → 写 storyboard.json

把 story-to-video.mjs 的核心逻辑（分句、prompt 模板、style_lock、character_lock）移植到
Python，把图像生成从 Codex Image2 / OpenAI API 改成 apiz CLI（默认 fal-ai/nano-banana-2）。

流程：
  1. splitStory：按 。！？； 切句，超长句按 ，、 和叙事转折词再切
  2. formatCaption：每句按 13 字/行 × 3 行格式化为字幕（含 \\n）
  3. 生成 character_reference（00_character_reference.png）
  4. 每句生成 master → apiz upload → 后续 master 用 image_url 引用保证一致性
  5. ffmpeg 切三层：text_image / bw / color
  6. 写 storyboard.json（含 narration 字段，供 gen_tts.py 用）

用法：
  python gen_story_images.py examples/story.txt --title "纸上的夏天"
  python gen_story_images.py examples/story.txt --title "..." --dry-run
  python gen_story_images.py examples/story.txt --title "..." --visual-plan plan.json
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib_apiz import generate_image as apiz_generate_image, upload as apiz_upload, DEFAULT_IMAGE_MODEL  # noqa: E402
from lib_agnes import generate_image as agnes_generate_image, DEFAULT_MODEL as AGNES_DEFAULT_MODEL  # noqa: E402

DEFAULT_BACKEND = "agnes"
DEFAULT_LANG = "zh"

# ============================================================================
# 风格锁定字符串（直接照抄 story-to-video.mjs）
# ============================================================================

STYLE_LOCK = (
    "minimalist Chinese diary comic reconstructed from the supplied reference video, "
    "pure white background, uneven black felt-tip pen outlines, naive wobbly proportions, "
    "rough dense black crayon scribbles for dark areas, sparse props, abundant negative space, "
    "selective muted wax-crayon color only, no realistic shading, no paper texture, no watermark"
)

# 英文教学模式风格锁：中小学英语课本风，非手绘日记漫画风
STYLE_LOCK_EN = (
    "clean English textbook illustration for middle school students, "
    "pure white background, clear readable black text, simple colorful flat illustration, "
    "educational flashcard layout like Oxford English textbook, "
    "soft bright educational colors, no realistic shading, no paper texture, no watermark"
)

DEFAULT_CHARACTER_LOCK = ""

# 英文关键词提取用的停用词表（用于从句子里挑出重点教学词汇）
ENGLISH_STOP_WORDS = frozenset({
    "the","a","an","is","are","was","were","be","been","being","am","do","does",
    "did","have","has","had","will","would","can","could","should","shall","may",
    "might","must","to","of","in","on","at","for","with","by","from","as","into",
    "about","than","then","so","very","too","and","but","or","if","because","when",
    "while","where","what","who","whom","which","how","why","this","that","these",
    "those","i","you","he","she","it","we","they","my","your","his","her","its",
    "our","their","me","him","us","them","not","no","yes","just","also","only",
    "there","here","up","down","out","over","again","once","all","any","some","one",
    "two","more","most","other","such","own","same","few","further","off","now",
    "get","got","go","goes","went","gone","come","came","say","said","make","made",
    "see","saw","know","knew","think","thought","let","like","want","well","back",
    "even","still","yet","ever","never","always","often","every","much","many",
})

# ============================================================================
# 分句算法（直接照抄 story-to-video.mjs 的 splitStory / splitLongBeat / formatCaption）
# ============================================================================

TERMINAL_PUNCT = re.compile(r"[。！？!?；;]$")
NARRATIVE_TURN = re.compile(
    r"^(后来|然后|接着|突然|可是|但是|但|却|于是|直到|最后|没想到|第二天|那天|这时)"
)


def hard_chunk(value: str, max_length: int = 36) -> list[str]:
    chunks = []
    remaining = value.strip()
    while len(remaining) > max_length:
        window = remaining[: max_length + 1]
        cut = max(window.rfind("，"), window.rfind("、"), window.rfind("；"))
        if cut < max_length * 0.55:
            cut = max_length
        else:
            cut += 1
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def split_long_beat(sentence: str, soft_limit: int = 36) -> list[str]:
    value = sentence.strip()
    if len(value) <= soft_limit:
        return [value]

    m = TERMINAL_PUNCT.search(value)
    ending = m.group(0) if m else ""
    body = value[: -len(ending)] if ending else value

    clauses = re.split(
        r"(?<=，|、)|(?=(?:后来|然后|接着|突然|可是|但是|但|却|于是|直到|最后|没想到|第二天|那天|这时))",
        body,
    )
    clauses = [c.strip() for c in clauses if c.strip()]
    if len(clauses) == 1:
        return hard_chunk(value, soft_limit)

    beats = []
    current = ""
    for clause in clauses:
        candidate = f"{current}{clause}"
        starts_new_beat = bool(NARRATIVE_TURN.match(clause)) and len(current) >= 12
        if current and (len(candidate) > soft_limit or starts_new_beat):
            beats.append(re.sub(r"[，、]$", "。", current))
            current = clause
        else:
            current = candidate
    if current:
        beats.append(f"{re.sub(r'[，、]$', '', current)}{ending or '。'}")
    return [b for beat in beats for b in hard_chunk(beat, soft_limit)]


def split_story(text: str) -> list[str]:
    normalized = re.sub(r"\r", "", re.sub(r"[ \t]+", " ", text)).strip()
    paragraphs = [p.strip() for p in re.split(r"\n+", normalized) if p.strip()]
    beats: list[str] = []
    for para in paragraphs:
        sentences = re.findall(r"[^。！？!?；;]+[。！？!?；;]?", para)
        for sent in sentences:
            beats.extend(split_long_beat(sent))
    return [
        (b if TERMINAL_PUNCT.search(b) else f"{b}。")
        for b in map(str.strip, beats)
        if b
    ]


def format_caption(text: str, max_chars_per_line: int = 13, max_lines: int = 3) -> str:
    lines = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= max_chars_per_line:
            lines.append(remaining)
            break
        window = remaining[: max_chars_per_line + 1]
        cut = max(window.rfind("，"), window.rfind("、"), window.rfind("；"), window.rfind("："))
        if cut < max_chars_per_line * 0.45:
            cut = max_chars_per_line
        else:
            cut += 1
        lines.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
        if remaining and re.match(r"^[。！？!?；;：:,，、]", remaining):
            lines[-1] += remaining[0]
            remaining = remaining[1:].strip()
    if len(lines) > max_lines:
        raise ValueError(
            f"Caption needs {len(lines)} lines (> {max_lines}); split story beat before rendering"
        )
    return "\n".join(lines)


def duration_for(caption: str) -> float:
    line_count = caption.count("\n") + 1
    char_count = len(caption.replace("\n", ""))
    return round(min(6.2, max(4.4, 3.8 + line_count * 0.48 + char_count * 0.035)), 1)


# ============================================================================
# 英文教学模式：英文分句 / 字幕格式化 / 关键词提取 / 估时
# ============================================================================

EN_TERMINAL_PUNCT = re.compile(r"[.!?;]$")
# 英文连接词，超长句按这些词切分
EN_TURN_SPLIT = re.compile(
    r"\s+(?:and|but|because|so|then|when|while|after|before|although|though|"
    r"since|unless|until|if|as|once|where|whereas)\b"
)


def split_long_beat_en(sentence: str, soft_limit: int = 120) -> list[str]:
    """英文超长句切分：先按逗号/分号/连接词切，再按词数硬切。"""
    value = sentence.strip()
    if len(value) <= soft_limit:
        return [value]

    m = EN_TERMINAL_PUNCT.search(value)
    ending = m.group(0) if m else ""
    body = value[: -len(ending)] if ending else value
    body = body.rstrip(",;: ")

    # 先按逗号/分号/冒号切
    clauses = re.split(r"(?<=[,;:])\s+", body)
    # 再按连接词切（and/but/because/...）
    expanded = []
    for clause in clauses:
        parts = EN_TURN_SPLIT.split(clause)
        expanded.extend(parts)
    clauses = [c.strip() for c in expanded if c.strip()]

    if len(clauses) == 1:
        # 硬切：按词数
        words = body.split()
        chunks = []
        cur = []
        cur_len = 0
        for w in words:
            add = len(w) + (1 if cur else 0)
            if cur and cur_len + add > soft_limit:
                chunks.append(" ".join(cur))
                cur = [w]
                cur_len = len(w)
            else:
                cur.append(w)
                cur_len += add
        if cur:
            chunks.append(" ".join(cur))
        result = chunks
    else:
        beats = []
        current = ""
        for clause in clauses:
            candidate = f"{current} {clause}".strip() if current else clause
            if current and len(candidate) > soft_limit:
                beats.append(current.rstrip(",;:"))
                current = clause
            else:
                current = candidate
        if current:
            beats.append(current.rstrip(",;:"))
        result = beats

    # 补尾标点
    return [b if EN_TERMINAL_PUNCT.search(b) else f"{b}{ending or '.'}" for b in result]


def split_story_en(text: str) -> list[str]:
    """英文故事分句：按空行分段，每段按 . ! ? ; 切句，超长句再切。"""
    normalized = re.sub(r"\r", "", re.sub(r"[ \t]+", " ", text)).strip()
    paragraphs = [p.strip() for p in re.split(r"\n+", normalized) if p.strip()]
    beats: list[str] = []
    for para in paragraphs:
        # 按句末标点 + 空白切句
        sentences = re.split(r"(?<=[.!?;])\s+", para)
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if not EN_TERMINAL_PUNCT.search(sent):
                sent = f"{sent}."
            beats.extend(split_long_beat_en(sent))
    return [b for b in beats if b]


def format_caption_en(text: str, max_chars_per_line: int = 42, max_lines: int = 3) -> str:
    """英文字幕格式化：按词换行，保持词完整。"""
    words = text.split()
    lines = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip() if current else w
        if len(candidate) > max_chars_per_line and current:
            lines.append(current)
            current = w
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        raise ValueError(
            f"Caption needs {len(lines)} lines (> {max_lines}); split story beat before rendering"
        )
    return "\n".join(lines)


def extract_keywords(sentence: str, max_n: int = 4) -> list[str]:
    """从英文句子里提取重点教学词汇（过滤停用词，按出现顺序去重）。

    用于在生图 prompt 里要求模型把关键词 + 音标注在图片上。
    """
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", sentence)
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in ENGLISH_STOP_WORDS or len(w) < 3:
            continue
        if lw in seen:
            continue
        seen.add(lw)
        result.append(w)
        if len(result) >= max_n:
            break
    return result


def duration_for_en(caption: str) -> float:
    """英文估时：英文朗读比中文慢，按词数给更多时间。"""
    line_count = caption.count("\n") + 1
    word_count = len(caption.split())
    return round(min(8.5, max(4.4, 3.0 + line_count * 0.6 + word_count * 0.28)), 1)


# ============================================================================
# apiz upload + 切三层（移植 import-codex-images.mjs 的 ffmpeg filter）
# ============================================================================

CAPTION_CROP_HEIGHT = 510
CAPTION_SCAN_HEIGHT = 600


def detect_caption_crop_y(master_path: Path, project_root: Path) -> int:
    """用 ffmpeg cropdetect 自动检测 caption 区域。失败时返回 0（top-aligned）。"""
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "verbose",
            "-loop", "1", "-i", str(master_path),
            "-vf",
            f"crop=1024:{CAPTION_SCAN_HEIGHT}:0:0,negate,format=gray,"
            f"lut=y='if(gt(val,80),255,0)',cropdetect=limit=0.1:round=2:reset=0",
            "-frames:v", "3", "-f", "null", "-",
        ],
        cwd=project_root, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    log = f"{proc.stdout}\n{proc.stderr}"
    matches = list(re.finditer(r"crop=(\d+):(\d+):(\d+):(\d+)", log))
    if proc.returncode != 0 or not matches:
        print(f"  ⚠️ caption bounds 检测失败: {master_path.name}，用 top-aligned")
        return 0
    last = matches[-1]
    content_h = int(last.group(2))
    content_y = int(last.group(4))
    centered = round(content_y + content_h / 2 - CAPTION_CROP_HEIGHT / 2)
    return max(0, min(CAPTION_SCAN_HEIGHT - CAPTION_CROP_HEIGHT, centered))


def ffmpeg_run(input_path: Path, vf: str, output: Path, project_root: Path) -> None:
    """跑 ffmpeg 单帧切图（用于 master → text/bw/color）。"""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
            "-vf", vf, "-frames:v", "1", "-y", str(output),
        ],
        cwd=project_root, check=True,
        encoding="utf-8", errors="replace",
    )


def _probe_size(path: Path) -> tuple[int, int]:
    """读图片宽高。失败返回 (0, 0)。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             str(path)],
            capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace",
        )
        w, h = out.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return 0, 0


def _normalize_master(master_path: Path, project_root: Path, text_mode_image2: bool) -> Path:
    """nano-banana-2 有时返回 416×624 而非 1024×1536；先 in-place upscale 到目标尺寸。

    text_mode_image2=True 目标 1024×1536，False 目标 1024×1024。
    若尺寸已正确，直接返回原路径。
    """
    target_w, target_h = (1024, 1536) if text_mode_image2 else (1024, 1024)
    w, h = _probe_size(master_path)
    if w == target_w and h == target_h:
        return master_path
    if w == 0 or h == 0:
        return master_path  # 探测失败，让下游 ffmpeg 自己报错
    # Log when upstream returned a smaller image. nano-banana-2 sometimes gives
    # 416×624 which upscales soft — but per the 70% rule this is acceptable and
    # must NOT prompt a rerun or a model switch. Just note it once.
    scale = max(target_w / max(w, 1), target_h / max(h, 1))
    if scale >= 1.5:
        print(
            f"  ℹ️ {master_path.name} 上游返回 {w}×{h}，自动放大到 {target_w}×{target_h}（偏软但可用，不需重跑）",
            file=sys.stderr,
        )
    tmp = master_path.with_suffix(".normalized.png")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", str(master_path),
         "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
         "-frames:v", "1", "-y", str(tmp)],
        cwd=project_root, check=True,
        encoding="utf-8", errors="replace",
    )
    tmp.replace(master_path)
    print(f"  ↑ master normalized {w}×{h} → {target_w}×{target_h}")
    return master_path


def split_master_into_layers(
    master_path: Path,
    asset_dir: Path,
    scene_id: str,
    project_root: Path,
    text_mode_image2: bool,
) -> dict[str, str | None]:
    """把一张 master 切成 text/bw/color 三层。返回相对路径（用于 storyboard）。

    image2 模式（含英文教学闪卡）：顶部切出 text_image（句子带），下方 1024×1024
    方形切 bw/color（插画区域，英文模式下音标作为小标注叠在这张图内）。font
    模式：不切 text_image，整张 master 出 bw/color。
    """
    _normalize_master(master_path, project_root, text_mode_image2)
    text_path = asset_dir / f"{scene_id}_text.png"
    bw_path = asset_dir / f"{scene_id}_bw.png"
    color_path = asset_dir / f"{scene_id}_color.png"

    rel = lambda p: f"assets/{p.relative_to(project_root / 'public' / 'assets').as_posix()}"

    if text_mode_image2:
        caption_y = detect_caption_crop_y(master_path, project_root)
        ffmpeg_run(
            master_path,
            f"crop=1024:{CAPTION_CROP_HEIGHT}:0:{caption_y},scale=1536:765:flags=lanczos",
            text_path, project_root,
        )

    # bw 层
    bw_filter = (
        "crop=1024:1024:0:512,format=gray,eq=contrast=1.18:brightness=0.035,unsharp=5:5:0.55:5:5:0"
        if text_mode_image2
        else "format=gray,eq=contrast=1.18:brightness=0.035,unsharp=5:5:0.55:5:5:0"
    )
    ffmpeg_run(master_path, bw_filter, bw_path, project_root)

    # color 层
    color_filter = "crop=1024:1024:0:512" if text_mode_image2 else "null"
    ffmpeg_run(master_path, color_filter, color_path, project_root)

    return {
        "text_image": rel(text_path) if text_mode_image2 else None,
        "bw": rel(bw_path),
        "detail": None,
        "color": rel(color_path),
    }


# ============================================================================
# Prompt 模板（直接照抄 story-to-video.mjs）
# ============================================================================

def build_character_reference_prompt(character_lock: str) -> str:
    return f"""Use case: illustration-story
Asset type: fixed protagonist character reference sheet for a hand-drawn Chinese diary-comic video
Input images: the supplied black-and-white and color frames are style references only. Ignore their people, composition and Chinese text.
Primary request: draw ONLY the recurring protagonists described below. Show each protagonist in two simple full-body poses, front view and three-quarter view, arranged side by side.
Character lock: {character_lock}
Style: {STYLE_LOCK}
Composition: pure white square canvas, all uncropped full-body poses centered with generous spacing and a clean white margin around all edges. No scenery, furniture, extra people, props or decorative marks.
Color: selective muted wax-crayon color only. Follow the clothing colors in the character lock, use black scribbles for hair and dark trousers, and leave skin and most of the canvas white.
Constraints: this is an identity reference only; no text, letters, numbers, labels, captions, speech bubbles, logo, signature or watermark; no realistic shading, gradients or vector cleanliness.""".strip()


def build_master_prompt(
    text: str,
    caption: str,
    visual_direction: str,
    character_lock: str,
    text_mode_image2: bool,
    has_character_ref: bool = False,
) -> str:
    # NOTE: do NOT put pixel coordinates (y=510), dimensions (1024x1024), or
    # percentages (10%) in the prompt — nano-banana-2 has been observed drawing
    # those numbers onto the card as visible text. The ffmpeg crop auto-detects
    # the text/illustration boundary, so relative layout descriptions suffice.
    master_shape = "tall portrait (top caption + bottom illustration)" if text_mode_image2 else "square canvas"
    if text_mode_image2:
        caption_panel = (
            f'Top copy panel (roughly the top third of the card): pure white background. '
            f'Write ONLY this Simplified Chinese caption verbatim, preserving the explicit line breaks:\n'
            f'"{caption}"\n'
            f'Use thick casual black felt-tip handwriting, one to three lines only, generous '
            f'left and right margins, and a large readable letter size. Do not put '
            f'any illustration or decorative mark in this top panel. Keep all text in the top '
            f'panel; do not write text inside the illustration area below.'
        )
        text_constraint = (
            "no extra text outside the exact top caption, no letters or numbers in the "
            "illustration, no labels, captions, speech bubbles, logo, signature or watermark, "
            "no stray coordinate numbers or measurement labels anywhere on the card"
        )
        illustration_panel = (
            "Illustration panel (the bottom two-thirds of the card, a square area below the text): "
            "use this area for the scene. Keep the top copy panel completely free of any illustration."
        )
    else:
        caption_panel = (
            "The caption will be rendered separately by the video player — do NOT draw any "
            "Chinese characters, English letters, numbers, labels, speech bubbles or writing "
            "of any kind anywhere on the canvas. Leave all text areas as blank white paper."
        )
        text_constraint = (
            "absolutely no text, Chinese characters, English letters, numbers, labels, "
            "captions, speech bubbles, calligraphy, handwriting, logo, signature or watermark. "
            "The narrative sentence below is for CONTENT REFERENCE ONLY and must not appear "
            "as written characters in the illustration"
        )
        illustration_panel = "Use the entire square canvas for the scene."

    if has_character_ref:
        input_images_line = (
            "Input images: the supplied original-video frames are style references; "
            "the fixed protagonist character sheet is the identity reference. Ignore all text in references."
        )
        protagonist_line = (
            "Create one concrete, immediately readable tableau for that sentence. "
            "Use the locked recurring protagonists whenever the current sentence requires them."
        )
        continuity_line = (
            "Continuity: preserve the locked character design. Use the fixed character sheet "
            "only for the protagonist's identity, never copy its pose or composition."
        )
    else:
        input_images_line = (
            "Input images: the supplied original-video frames are style references only. Ignore all text in references."
        )
        protagonist_line = "Create one concrete, immediately readable tableau for that sentence."
        continuity_line = ""

    isolation_block = (
        "\nNarrative isolation: show only people required by the current sentence."
        if has_character_ref else ""
    )

    # In font mode the caption is rendered by Remotion (TextWipe). agnes sees
    # raw Chinese in the prompt and "helpfully" draws it as handwriting on the
    # master, causing a double-caption. When an English visual_direction is
    # supplied (i.e. --visual-plan), omit the Chinese sentence entirely — the
    # English steering is enough and this is verified to keep the canvas
    # text-free. Only feed Chinese when there's no visual_plan or in image2
    # mode (where the model IS expected to draw the caption panel).
    if text_mode_image2:
        narrative_line = f'Narrative sentence to illustrate (use its exact words for the top caption): "{text}"'
    elif visual_direction.strip():
        narrative_line = (
            "Narrative content is conveyed by the English Scene direction below. "
            "Do NOT write any Chinese characters, English letters or sentence on "
            "the canvas — the caption is added later by the video player."
        )
    else:
        narrative_line = (
            f'Content to depict VISUALLY — do NOT write or letter any of these '
            f'characters on the canvas; the caption is added later: "{text}"'
        )

    return f"""Use case: illustration-story
Asset type: one vertical production master ({master_shape}) for a hand-drawn Chinese diary-comic video. This single output will be locally split into a handwritten caption plate and a color illustration plate.
{input_images_line}
{narrative_line}
Scene direction: {visual_direction}
{protagonist_line}
{character_lock}
Style: {STYLE_LOCK}
{caption_panel}
{illustration_panel}
Composition: use a comfortably wide camera view. Keep the scene in the lower-middle of its illustration area with generous white negative space. Leave a clean white margin around all edges so no visible mark touches the frame.
Color: selective muted wax-crayon color only: sage green, dusty blue, warm tan, brick red and warm yellow. Keep hair, trousers and dark areas as black scribbles. Leave skin and most of the canvas pure white.
{continuity_line}{isolation_block}
Constraints: non-graphic, emotionally restrained family storytelling; no visible blood or injury; {text_constraint}; no graphite realism, gradients or vector cleanliness.""".strip()


# ============================================================================
# 英文教学模式：教育闪卡 prompt（句子 + 关键词音标 + 插画 烧在图上）
# ============================================================================

def build_english_flashcard_prompt(
    sentence: str,
    keywords: list[str],
    visual_direction: str,
) -> str:
    """构建英文教学闪卡 master prompt。

    Oxford 英语课本风格，**两段式**布局（不是满屏）：
      - 顶部文字带：只有英文句子（大字，1-2 行），纯白背景
      - 下方方形插画：彩色插画填满；关键词+IPA 音标以**小字体**叠在插画
        左下角（不是单独一行，也不在顶部带里），作为画面上的小标注

    这样 ffmpeg 在文字带/插画之间做水平裁切时，切线上只有纯白（句子在切
    线之上、音标在插画区域内），不会再从音标行中间截断。顶部句子带由
    TextWipe 第 0 帧揭示，所以每场开头不会全白等待。

    生图要求：
      - 顶部：只写句子，不要把音标/关键词放进顶部带
      - 下方插画：关键词+音标小字号叠在插画左下角，左对齐竖排，次要于画面
      - 左下角保持干净明亮，保证小音标可读
      - 不要水平分隔线、面板边框
      - Style like Oxford English textbook
    """
    if keywords:
        keywords_line = ", ".join(keywords)
        label_block = (
            "- Draw the keywords and their IPA phonetics as SMALL labels overlaid ON the illustration, "
            "stacked in the bottom-left corner of the illustration square. Each keyword is followed by its "
            "IPA in a small clean font. Keep them small and clearly secondary to the picture (do not make a "
            "separate text row or a caption band for them).\n"
            "- Compose the illustration so its bottom-left corner stays light and uncluttered (open sky, a "
            "plain wall, pale ground, or clean paper) so the small phonetic labels stay legible. Do not place "
            "busy details or dark shapes behind the labels."
        )
        design_line = "- Large readable English sentence at top, small keyword/IPA labels on the picture"
        constraints_line = (
            "Constraints: educational, family-friendly content; the English text and phonetic symbols MUST be "
            "clearly legible and spelled correctly; no watermark, no signature, no logo, no speech bubbles, no "
            "stray numbers or measurement labels, no panel borders or dividing lines; no realistic shading or gradients."
        )
    else:
        keywords_line = "(none — no keywords or labels of any kind)"
        label_block = (
            "- The illustration area must be a PURE PICTURE with NO text of any kind: no keywords, no labels, "
            "no captions, no words, no letters, no numbers, no signs with writing, no document text, no names "
            "on objects. Do not draw any written characters anywhere in the illustration. All written English "
            "belongs ONLY in the top sentence band."
        )
        design_line = "- Large readable English sentence at top, pure text-free illustration below"
        constraints_line = (
            "Constraints: educational, family-friendly content; the English sentence at top MUST be clearly "
            "legible and spelled correctly; the illustration below must contain ABSOLUTELY NO text, letters, "
            "numbers, labels, captions, signs, or written characters of any kind; no watermark, no signature, "
            "no logo, no speech bubbles, no stray measurement labels, no panel borders or dividing lines; no "
            "realistic shading or gradients."
        )

    # NOTE: do NOT put pixel coordinates (y=510), dimensions (1024x1024), or
    # percentages (10%, 8%) in this prompt. nano-banana-2 has been observed
    # literally drawing those numbers onto the card as visible text. Use
    # relative layout descriptions ("top third", "bottom two-thirds"). The
    # ffmpeg crop is post-processing, never put in the prompt.
    return f"""Use case: educational-illustration
Asset type: one tall portrait production master for an English teaching flashcard video. The top is locally split off as a caption plate; the bottom becomes a square illustration plate from which a grayscale sketch is derived.
Input images: the supplied reference frames are style references only. Ignore their text and people.

English textbook flashcard page for middle school students.

CONTENT:
Sentence: "{sentence}"
Keywords (each followed by its IPA phonetic transcription): {keywords_line}

LAYOUT:
- Top copy band (roughly the top third of the card): pure white background. Write ONLY the English sentence here, in a large readable black sans-serif font, one or two lines, generous left and right margins. This top band contains NO keywords and NO phonetics.
- Illustration area (the bottom two-thirds, a square below the sentence): fill this whole square with a simple colorful illustration.
{label_block}
- Do NOT draw any horizontal dividing line or panel border between the sentence and the illustration.
- Illustration subject: {visual_direction}

DESIGN:
{design_line}
- Simple colorful illustration related to sentence meaning
- Clean educational layout, portrait orientation
- Style like Oxford English textbook

Composition: leave a clear white margin around all edges so no drawn element touches the frame edge.
Color: soft bright educational colors — sage green, dusty blue, warm tan, brick red, warm yellow. No pure neon or fluorescent colors.
{constraints_line}""".strip()


# ============================================================================
# 主流程
# ============================================================================

def safe_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title)
    cleaned = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE)
    return cleaned.strip("-")[:32] or "story"


# apiz enforces an account-level minimum balance (~10 yuan) before accepting
# image generation jobs. Below it every call returns HTTP 429 mid-batch, which
# used to look like 16 random failures. Query the balance once up front so the
# user gets one clear message instead.
APIZ_MIN_BALANCE_YUAN = 10.0


def apiz_preflight_balance() -> None:
    """Check apiz balance before starting a batch. Warns but does not block if
    the CLI is missing, times out, or returns unexpected output. Fails hard
    only when balance is unambiguously below the apiz minimum."""
    try:
        proc = subprocess.run(
            ["apiz", "account", "balance", "--json"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        print("  ⚠️ 未找到 apiz CLI，跳过余额预检查", file=sys.stderr)
        return
    except subprocess.TimeoutExpired:
        print("  ⚠️ apiz 余额查询超时，跳过预检查", file=sys.stderr)
        return
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()[:200]
        print(f"  ⚠️ apiz 余额查询失败（跳过）：{msg}", file=sys.stderr)
        return
    try:
        data = json.loads(proc.stdout)
        yuan = float(data.get("balance_yuan", 0))
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"  ⚠️ apiz 余额返回解析失败（跳过）：{e}", file=sys.stderr)
        return
    if yuan < APIZ_MIN_BALANCE_YUAN:
        raise SystemExit(
            f"apiz 余额不足：当前 {yuan:.2f} 元，"
            f"nano-banana-2 要求账户至少 {APIZ_MIN_BALANCE_YUAN:.0f} 元。\n"
            f"  充值后重跑（脚本会跳过已成功的场次），或改用 --backend agnes（免费）。"
        )
    print(f"  ℹ️ apiz 余额：{yuan:.2f} 元（OK）")


def main():
    parser = argparse.ArgumentParser(
        description="故事文本 → agnes/apiz 生成 master → ffmpeg 切三层 → storyboard.json",
    )
    parser.add_argument("input", help="story.txt 路径（UTF-8）")
    parser.add_argument(
        "--backend", choices=["agnes", "apiz"], default=DEFAULT_BACKEND,
        help=f"图片后端：agnes Agnes Image 2.1 Flash 默认且免费 / apiz fal-ai/nano-banana-2 收费",
    )
    parser.add_argument(
        "--lang", choices=["zh", "en"], default=DEFAULT_LANG,
        help="语言模式：zh 中文手绘日记风（默认）/ en 英文教学闪卡风（句子+关键词音标+插画烧在图上，用于英语教学）",
    )
    parser.add_argument("--title", default="手绘故事", help="故事标题（用于资产目录命名）")
    parser.add_argument(
        "--character-lock", default=DEFAULT_CHARACTER_LOCK,
        help="角色一致性约束（默认通用版）",
    )
    parser.add_argument(
        "--visual-plan", help="可选 visual_plan.json（场景 id → 视觉方向）",
    )
    parser.add_argument(
        "--text-mode", choices=["image2", "font"], default=None,
        help="caption 渲染方式：image2（图片模型画手写体，仅 apiz 支持） / font（MaShanZheng 字体，agnes 必须用这个）。不传时按后端自动选：agnes→font，apiz→image2",
    )
    parser.add_argument(
        "--transition", choices=["cut", "page-flip"], default="cut",
        help="转场：cut 直接切（默认） / page-flip 右下角卷页",
    )
    parser.add_argument(
        "--transition-sec", type=float, default=0.7,
        help="page-flip 转场秒数（0–2，默认 0.7）",
    )
    parser.add_argument(
        "--model", default=DEFAULT_IMAGE_MODEL,
        help=f"apiz 模型 id（默认 {DEFAULT_IMAGE_MODEL}）",
    )
    parser.add_argument(
        "--character-ref", action="store_true",
        help="生成 00_character_reference.png 并用作图生图参考（默认关闭：纯文生图，避免角色立绘污染）",
    )
    parser.add_argument(
        "--character-ref-image", default=None,
        help="用户提供的角色参考图路径（开启图生图锁身份，跳过自动生成 00）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印 prompt 和计划，不实际生成图片",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="已存在的 master 也重新生成（默认跳过）",
    )
    parser.add_argument(
        "--concurrency", type=int, default=4,
        help="master 并发生成数（默认 4；agnes/apiz 是 IO 密集型，并发可把 15 张图时间砍到 1/4）",
    )
    args = parser.parse_args()

    # text_mode 未显式指定时按后端+语言自动选：
    #   zh + agnes → font（agnes 不会画中文）
    #   zh + apiz  → image2
    #   en         → image2（英文教学闪卡必须由模型把句子+关键词音标画在图上）
    if args.text_mode is None:
        if args.lang == "en":
            args.text_mode = "image2"
            print(f"  ℹ️ --lang en 模式，强制 text_mode=image2（模型画教学闪卡文字）")
            if args.backend == "agnes":
                print(f"  ⚠️ agnes + image2 可能会把插画画满整个画布（已知问题）。")
                print(f"     英文教学闪卡推荐用 --backend apiz（nano-banana-2 文字渲染更稳）。")
                print(f"     如坚持用 agnes，接受 70% 文字质量即可，不要逐张修。")
        else:
            args.text_mode = "font" if args.backend == "agnes" else "image2"
            print(f"  ℹ️ --text-mode 未指定，按后端 {args.backend} 自动选 {args.text_mode}")

    project_root = Path.cwd()
    story_path = Path(args.input).resolve()
    if not story_path.exists():
        raise SystemExit(f"故事文件不存在: {story_path}")

    source_text = story_path.read_text(encoding="utf-8")
    if args.lang == "en":
        story_parts = split_story_en(source_text)
    else:
        story_parts = split_story(source_text)
    if not story_parts:
        raise SystemExit("故事文本里没找到可用句子")

    print(f"分句完成：{len(story_parts)} 句")
    for i, part in enumerate(story_parts, 1):
        print(f"  {i:02d}. {part}")

    # 计算资产目录 hash（避免不同故事冲突）
    hash_input = "\n".join([
        f"{args.backend}-{args.lang}-v1",
        args.title,
        args.text_mode,
        args.transition,
        str(args.transition_sec),
        args.character_lock,
        source_text,
    ])
    story_hash = hashlib.sha256(hash_input.encode("utf-8")).digest().hex()[:8]
    asset_set = f"{safe_title(args.title)}-{story_hash}"
    asset_dir = project_root / "public" / "assets" / "generated" / asset_set
    prompt_dir = project_root / "prompts" / asset_set
    asset_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n资产目录: public/assets/generated/{asset_set}/")

    # 校验参考图存在（apiz generate --image-url 需要它们做风格锚点）
    ref_bw = project_root / "references" / "style-bw.png"
    ref_color = project_root / "references" / "style-color.png"
    if not (ref_bw.exists() and ref_color.exists()):
        raise SystemExit(
            f"缺少风格参考图: {ref_bw} / {ref_color}\n"
            f"模板应自带这两张图（来自 story-to-handdrawn-video-main/references/）"
        )

    visual_plan = {}
    if args.visual_plan:
        visual_plan = json.loads(Path(args.visual_plan).read_text(encoding="utf-8"))

    # apiz 余额预检查：在烧 16 张图之前确认账户有钱，避免批到一半 429。
    if args.backend == "apiz" and not args.dry_run:
        apiz_preflight_balance()

    # —— Step 1: character_reference（默认关闭，纯文生图）——
    # 只有 --character-ref（自动生成 00）或 --character-ref-image（用户提供）才开启图生图
    char_ref_url = None  # apiz CDN URL（仅 apiz 后端用）
    char_ref_path = None
    use_character_ref = False

    if args.character_ref_image:
        # 用户提供参考图
        user_ref = Path(args.character_ref_image).resolve()
        if not user_ref.exists():
            raise SystemExit(f"--character-ref-image 文件不存在: {user_ref}")
        char_ref_path = user_ref
        use_character_ref = True
        print(f"\n✓ 使用用户提供的角色参考图: {user_ref.name}")
    elif args.character_ref:
        # 自动生成 00_character_reference.png
        char_ref_path = asset_dir / "00_character_reference.png"
        use_character_ref = True
        if char_ref_path.exists() and not args.force:
            print(f"\n✓ character_reference 已存在，跳过（--force 可重生成）")
        else:
            char_prompt = build_character_reference_prompt(args.character_lock)
            (prompt_dir / "00_character_reference.txt").write_text(
                char_prompt + "\n", encoding="utf-8"
            )
            if args.dry_run:
                print("\n[dry-run] character_reference prompt:")
                print(char_prompt[:300] + "...")
            else:
                print(f"\n生成 character_reference ({args.backend}) ...")
                if args.backend == "agnes":
                    agnes_generate_image(
                        prompt=char_prompt,
                        out_path=char_ref_path,
                        model=AGNES_DEFAULT_MODEL,
                        size="2K",
                        ratio="1:1",
                    )
                else:
                    apiz_generate_image(
                        prompt=char_prompt,
                        out_path=char_ref_path,
                        model=args.model,
                        image_size="square_hd",
                    )
        if char_ref_path.exists() and args.backend == "apiz":
            print("上传 character_reference 到 apiz CDN（给后续 master 当参考）...")
            try:
                char_ref_url = apiz_upload(char_ref_path, folder="story-handdrawn")
                print(f"  ✓ {char_ref_url}")
            except RuntimeError as e:
                print(f"  ⚠️ 上传失败 ({e})，后续 master 将不带 character 参考图")
                char_ref_url = None
    else:
        print(f"\nℹ️  未启用 character_reference（默认纯文生图）。"
              f"如需角色锁，加 --character-ref 或 --character-ref-image <path>")

    # —— Step 2: 每句生成 master + 切三层 ——
    # 先组装每场计划（prompt/path/caption/keywords），再并发生成 master（IO 密集），
    # 最后串行切三层 + 拼 storyboard。并发把 15 张图的墙钟时间砍到约 1/N。
    is_en = (args.lang == "en")
    scene_plans = []
    for i, text in enumerate(story_parts, 1):
        sid = f"{i:02d}"
        if is_en:
            caption = format_caption_en(text)
            duration = duration_for_en(caption)
            keywords = extract_keywords(text)
        else:
            caption = format_caption(text)
            duration = duration_for(caption)
            keywords = []
        # visual_plan 支持两种格式：
        #   纯字符串："01": "A rabbit in a meadow"（直接当视觉方向）
        #   英文模式 dict："01": {"direction": "...", "keywords": ["word1"]}（覆盖关键词）
        vp_entry = visual_plan.get(sid)
        if isinstance(vp_entry, dict):
            visual_direction = str(vp_entry.get("direction", ""))
            if is_en and "keywords" in vp_entry:
                keywords = list(vp_entry["keywords"])
        else:
            visual_direction = str(
                vp_entry
                or ("A simple colorful illustration related to the sentence meaning, clean educational style."
                    if is_en
                    else "Stage one simple visual beat that expresses only the current sentence.")
            )
        master_path = asset_dir / f"{sid}_master.png"
        if is_en:
            prompt = build_english_flashcard_prompt(
                sentence=text, keywords=keywords, visual_direction=visual_direction,
            )
        else:
            prompt = build_master_prompt(
                text=text, caption=caption, visual_direction=visual_direction,
                character_lock=args.character_lock, text_mode_image2=(args.text_mode == "image2"),
                has_character_ref=use_character_ref,
            )
        (prompt_dir / f"{sid}_master.txt").write_text(prompt + "\n", encoding="utf-8")
        plan_entry = {
            "sid": sid, "text": text, "caption": caption,
            "duration": duration, "master_path": master_path, "prompt": prompt,
        }
        if is_en:
            plan_entry["keywords"] = keywords
        scene_plans.append(plan_entry)

    def _gen_master(plan):
        # Returns (sid, error). The error path matters: as_completed() alone
        # does NOT re-raise worker exceptions, so without capturing them here
        # a failed apiz call (balance 429, network timeout, ...) used to look
        # like success while leaving an empty asset directory.
        sid = plan["sid"]
        master_path = plan["master_path"]
        if args.dry_run:
            print(f"\n[{sid}] [dry-run] prompt first 200 chars: {plan['prompt'][:200]}...")
            return sid, None
        if master_path.exists() and not args.force:
            print(f"[{sid}] master 已存在，跳过")
            return sid, None
        print(f"[{sid}] 生成 master ({args.backend}) ...")
        try:
            if args.backend == "agnes":
                agnes_generate_image(
                    prompt=plan["prompt"], out_path=master_path,
                    model=AGNES_DEFAULT_MODEL, size="2K", ratio="2:3",
                    image_ref=char_ref_path if (char_ref_path and char_ref_path.exists()) else None,
                )
            else:
                apiz_generate_image(
                    prompt=plan["prompt"], out_path=master_path, model=args.model,
                    image_size="portrait_4_3", image_url=char_ref_url,
                )
            # apiz CLI has been observed returning exit 0 without writing a
            # file when the account is below the minimum balance. Verify the
            # file actually landed and is non-trivial before declaring success,
            # otherwise the missing file silently propagates into a broken
            # render hours later.
            size = master_path.stat().st_size if master_path.exists() else 0
            if size < 1024:
                raise RuntimeError(
                    f"generation reported success but {master_path.name} "
                    f"is missing or empty (size={size})"
                )
            print(f"[{sid}] ✓ done")
            return sid, None
        except Exception as e:
            return sid, e

    if not args.dry_run:
        todo = [p for p in scene_plans if args.force or not p["master_path"].exists()]
        if todo:
            workers = max(1, min(args.concurrency, len(todo)))
            print(f"\nℹ️  并发生成 {len(todo)} 张 master（workers={workers}）...")
            failures: list[tuple[str, Exception]] = []
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_gen_master, p) for p in todo]
                for fut in as_completed(futures):
                    sid, err = fut.result()
                    if err is not None:
                        failures.append((sid, err))
                        print(f"[{sid}] ✗ {err}", file=sys.stderr)
            if failures:
                hints = []
                if args.backend == "apiz":
                    hints.append(
                        "apiz 余额不足？跑 `apiz account balance` 检查"
                        "（nano-banana-2 要求账户至少 10 元）"
                    )
                hints.append("网络/模型临时不可用？重跑脚本会自动跳过已成功的场次")
                hint_text = "\n  ".join(hints)
                failed_ids = ", ".join(sid for sid, _ in failures)
                raise SystemExit(
                    f"\n✗ {len(failures)}/{len(todo)} 张 master 生成失败：{failed_ids}\n"
                    f"  {hint_text}"
                )
        else:
            print("\nℹ️  所有 master 已存在，跳过生成")

    # 串行切三层 + 拼 scenes（ffmpeg 各自独立文件，但保持输出顺序稳定）
    scenes = []
    for plan in scene_plans:
        sid = plan["sid"]
        if not args.dry_run and plan["master_path"].exists():
            assets = split_master_into_layers(
                master_path=plan["master_path"], asset_dir=asset_dir, scene_id=sid,
                project_root=project_root, text_mode_image2=(args.text_mode == "image2"),
            )
        else:
            assets = {
                "text_image": (
                    f"assets/generated/{asset_set}/{sid}_text.png" if args.text_mode == "image2" else None
                ),
                "bw": f"assets/generated/{asset_set}/{sid}_bw.png",
                "detail": None,
                "color": f"assets/generated/{asset_set}/{sid}_color.png",
            }
        scene_layers = ["text", "bw_full", "color"]
        scene_entry = {
            "id": sid,
            "duration_sec": plan["duration"],
            "text": plan["caption"],
            "narration": plan["text"],
            "visual": (
                f"English textbook flashcard: sentence in the top band, simple colorful illustration below; "
                f"keywords with IPA phonetics are small labels overlaid on the bottom-left of the illustration. "
                f"Sentence: {plan['text']}"
                if is_en
                else f"根据文案绘制一个单一、清楚、可画的白底日记漫画场景：{plan['text']}"
            ),
            "shot": "story_beat",
            "layers": scene_layers,
            "color_hint": (
                "Soft bright educational colors — sage green, dusty blue, warm tan, brick red, warm yellow; keep most of the canvas clean white"
                if is_en
                else "仅使用元视频的鼠尾草绿、灰蓝、浅棕、砖红、暖黄等低饱和蜡笔色，保留大量纯白"
            ),
            "detail_hint": None,
            "assets": assets,
        }
        if is_en:
            scene_entry["keywords"] = plan.get("keywords", [])
        scenes.append(scene_entry)

    # —— Step 3: 写 storyboard.json ——
    storyboard = {
        "project": {
            "title": args.title,
            "lang": args.lang,
            "mode": "speed",
            "images_per_scene": 1,
            "derive_bw": "local",
            "enable_detail": False,
            "gen_size": 1024,
            "export_size": [1080, 1440],
            "ratio": "3:4",
            "width": 1080,
            "height": 1440,
            "fps": 30,
            "transition": args.transition,
            "transition_sec": args.transition_sec,
            "style_lock": STYLE_LOCK_EN if is_en else STYLE_LOCK,
            "character_lock": args.character_lock,
            "image_generator": f"{args.backend}-{'agnes-image-2.1-flash' if args.backend == 'agnes' else 'nano-banana-2'}",
            "audio": {
                "voiceover": "pending",  # 跑完 gen_tts + apply_timeline 后变 'active'
                "default_backend": "edge",  # 免费 edge-tts；要高质量加 --backend minimax
                "default_voice": "en-US-JennyNeural" if is_en else "zh-CN-XiaoyiNeural",
                "bgm": "optional_bed_only",
                "bgm_follows_text": False,
            },
        },
        "scenes": scenes,
    }

    out_path = project_root / "storyboard.json"
    out_path.write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{'='*60}")
    print(f"✓ storyboard 写入 {out_path}")
    print(f"  语言: {args.lang} | 场景数: {len(scenes)}")
    print(f"  转场: {args.transition}" + (f" ({args.transition_sec}s)" if args.transition == "page-flip" else ""))
    if is_en:
        print(f"  英文教学模式：每张图含句子+关键词音标+插画（教育闪卡）")
        print(f"  TTS 用 en-US-JennyNeural（narration.yaml voice 字段）")
    if args.dry_run:
        print("\n[dry-run] 没有实际生成图片。去掉 --dry-run 跑实际生成。")
    else:
        print("\n下一步：")
        print("  1. python ../../scripts/gen_tts.py narration.yaml --out-dir public/audio/narration")
        print("  2. python ../../scripts/apply_timeline.py")
        print("  3. npm run render:preview  # 720×960 预览")


if __name__ == "__main__":
    main()
