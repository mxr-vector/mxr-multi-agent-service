"""
agent/skills 技能包只读 loader 与剧本生成风格注册表（story-ai-workspace）。

技能包（agent/skills/<name>/SKILL.md + references/）是静态知识资产：本模块
只读加载技能包文本文件，供生成模型经 skill_read 工具按需读取——渐进披露：
模型生成前先阅读 SKILL.md 全文，再按 SKILL.md 内的指引读取 references 参考
资料；绝不执行技能包内脚本，绝不越出技能包目录读取。

风格注册表把"用户可见的视频风格"绑定到技能知识源、画幅预设与可读文件清单：
- generic       → seedance-storyboard-generator（通用短剧，风格开放）
- shangmeiying  → smy-seedance-storyboard-main（上美影动画，风格锁定）
- handdrawn     → story-handdrawn-remotion-main（手绘日记）
story-handdrawn-video-main 与 remotion 版同属手绘家族且为脚本链路变体，
不单独暴露（并入手绘日记知识源）。

可读文件清单为逐风格评估结论（内容创作相关全纳入，工程实现类剔除，如
handdrawn 的 Remotion 组件 API 不入清单）：注册表内显式维护（相对路径,
一句话用途），经 readable_file_hint 注入提示词，read_skill_file 按技能包
目录边界 + 后缀白名单双重校验读取。
"""

from dataclasses import dataclass, field
from pathlib import Path

from exception.bad_except import bad_except
from utils.logger import logger

# 技能包根目录（agent/skills/）
SKILLS_ROOT = Path(__file__).resolve().parent

# 可读文件后缀白名单（技能包内文本资料；图片/脚本等工程资源不可读）
_READABLE_SUFFIXES = (".md", ".txt")
# 单次读取字符上限（防御异常大文件挤爆输入预算；远超现存最大 reference 体积）
_READ_MAX_CHARS = 256 * 1024


@dataclass(frozen=True)
class StyleEntry:
    """注册表条目：风格 key → 技能知识源 + 画幅预设 + 可读文件清单。"""

    key: str
    name: str
    description: str
    skill_dir: str
    aspect_ratios: tuple[str, ...]
    # 可读文件清单：(技能包内相对路径, 一句话用途)；顺序即提示词清单顺序
    readable_files: tuple[tuple[str, str], ...] = field(default=())


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
            readable_files=(
                ("SKILL.md", "技能主文档：完整工作流、剧本格式规范与资产出图提示词规则（生成前必读）"),
                ("references/好剧本.md", "优秀剧本范例（核心梗/故事梗概/一句话卖点的结构示范）"),
                ("references/seedance-manual.md", "Seedance 2.0 平台手册与分镜提示词模板"),
                ("references/分镜优化与声音设计.md", "分镜优化与声音设计进阶指南"),
                ("references/优化分镜.md", "分镜优化速查"),
                ("references/故事转视频脚本-转换工具.md", "剧本转视频脚本的转换工具说明"),
            ),
        ),
        StyleEntry(
            key="shangmeiying",
            name="上美影动画",
            description="上美影复古手绘动画风格（水墨线条/矿物颜料平涂），"
            "剧组色盘声明，国风短剧专用",
            skill_dir="smy-seedance-storyboard-main",
            aspect_ratios=("9:16", "16:9", "4:3"),
            readable_files=(
                ("SKILL.md", "技能主文档：上美影工作流、剧本格式与资产提示词规则（生成前必读）"),
                ("references/上美影风格指南.md", "风格唯一权威定义：风格块/色盘/造型规范/资产模板（涉风格内容均以此为准）"),
                ("references/上美影原始提示词.txt", "上美影原始 Midjourney 实测提示词素材"),
                ("references/seedance-manual.md", "Seedance 2.0 平台手册与分镜提示词模板（含上美影国风动画模板）"),
                ("references/好剧本.md", "优秀剧本范例（核心梗/故事梗概/一句话卖点的结构示范）"),
                ("references/分镜优化与声音设计.md", "分镜优化与声音设计进阶指南"),
                ("references/优化分镜.md", "分镜优化速查"),
                ("references/故事转视频脚本-转换工具.md", "剧本转视频脚本的转换工具说明"),
            ),
        ),
        StyleEntry(
            key="handdrawn",
            name="手绘日记",
            description="手绘日记漫画风（白底+记号笔轮廓+蜡笔色），一句一拍"
            "竖屏叙事，适合生活叙事/绘本/教学小品",
            skill_dir="story-handdrawn-remotion-main",
            aspect_ratios=("3:4", "9:16"),
            readable_files=(
                ("SKILL.md", "技能主文档：手绘日记风格 DNA、一句一拍叙事规范与视觉规划（生成前必读）"),
                ("references/prompt-recipes.md", "apiz nano-banana-2 生图 prompt 配方与硬规则（style_lock/角色锁定/安全边距）"),
                ("references/pipeline.md", "制作管线详解（三种输入模式、一句一拍叙事布局展开）"),
            ),
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


def readable_file_hint(style: StyleEntry) -> str:
    """生成注入提示词的可读文件清单文本（`- path — 用途` 行式）。"""
    return "\n".join(f"- {path} — {usage}" for path, usage in style.readable_files)


def read_skill_file(skill_dir: str, rel_path: str) -> str:
    """读取技能包内文本文件（skill_read 工具的实现原语）。

    三重校验：路径 resolve 后必须仍在技能包目录内（防 ../ 越界与绝对路径
    逃逸）；后缀须在 .md/.txt 白名单（图片/脚本/配置不可读）；文件须存在。
    不抛异常——错误以文本返回供模型阅读纠偏，不阻断生成流。
    """
    skill_root = (SKILLS_ROOT / skill_dir).resolve()
    if not skill_root.is_dir():
        logger.warning(f"[SKILL] 技能包目录缺失: {skill_root}（检查部署是否漏拷 agent/skills）")
        return f"技能包不存在：{skill_dir}。"
    target = (skill_root / (rel_path or "")).resolve()
    if not target.is_relative_to(skill_root):
        logger.warning(f"[SKILL] 拒绝越界读取: {skill_dir}/{rel_path}")
        return f"读取被拒绝：{rel_path} 越出技能包目录。"
    if target.suffix.lower() not in _READABLE_SUFFIXES:
        return f"读取被拒绝：{rel_path} 不是可读的文本资料（仅支持 .md/.txt）。"
    if not target.is_file():
        return f"文件不存在：{rel_path}。请从技能包文件清单中选择。"
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"[SKILL] 文件读取失败 {skill_dir}/{rel_path}: {exc}")
        return f"文件读取失败：{rel_path}。"
    if len(text) > _READ_MAX_CHARS:
        return text[:_READ_MAX_CHARS] + f"\n\n（内容过长已截断，仅显示前 {_READ_MAX_CHARS} 字符）"
    return text


if __name__ == "__main__":
    # 冒烟：三风格清单枚举 + 正常读取 + 越界/后缀/不存在三类拒绝（纯文件读取，无需配置快照）
    assert [s["key"] for s in list_styles()] == ["generic", "shangmeiying", "handdrawn"]
    style = get_style("shangmeiying")
    logger.info("可读文件清单：\n" + readable_file_hint(style))
    for path, _usage in style.readable_files:
        text = read_skill_file(style.skill_dir, path)
        assert text and not text.startswith("读取被拒绝"), f"正常读取失败: {path}"
        logger.info(f"读取 OK：{path}（{len(text)} 字符）")
    assert "越出技能包目录" in read_skill_file(style.skill_dir, "../../env/.env.development")
    assert "越出技能包目录" in read_skill_file(style.skill_dir, "/etc/hostname")
    assert "不是可读的文本资料" in read_skill_file(style.skill_dir, "SKILL.md.bak")
    assert "文件不存在" in read_skill_file(style.skill_dir, "references/不存在.md")
    try:
        get_style("nope")
    except Exception as exc:
        logger.info(f"未注册风格拒绝：{exc}")
    else:
        raise AssertionError("未注册风格未被拒绝")
    logger.info("loader 冒烟通过")
