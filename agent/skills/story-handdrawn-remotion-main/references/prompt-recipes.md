# apiz nano-banana-2 Prompt 配方

> 这是给 `gen_story_images.py` 的 prompt 工程参考。脚本已经内置了完整 prompt，本文档解释每个字段为什么这么写。

## 一、style_lock（视觉风格锁，全文照抄，一个字不要改）

```
minimalist Chinese diary comic reconstructed from the supplied reference video,
pure white background, uneven black felt-tip pen outlines, naive wobbly proportions,
rough dense black crayon scribbles for dark areas, sparse props, abundant negative space,
selective muted wax-crayon color only, no realistic shading, no paper texture, no watermark
```

**为什么这么长**：每个短语锁一个视觉维度：
- `pure white background` → 锁底色（防止 apiz 加米黄/渐变）
- `uneven black felt-tip pen outlines` → 锁线条（记号笔粗细变化）
- `naive wobbly proportions` → 锁比例（业余感、不对称）
- `rough dense black crayon scribbles for dark areas` → 锁阴影（涂黑而非渐变）
- `sparse props, abundant negative space` → 锁密度（不要塞满）
- `selective muted wax-crayon color only` → 锁色彩（蜡笔感、低饱和）
- `no realistic shading, no paper texture, no watermark` → 三道禁止

## 二、character_lock（角色一致性约束）

### 写法模板

```
固定 [N] 位主角：
[角色 A]：年龄，发型/脸型，[上装颜色+款式]，[下装颜色+款式]，[鞋]；
[角色 B]：年龄，...

两人的脸型、发型、年龄、服装配色和身体比例在所有场景必须一致；
[特殊规则，如：母亲只允许以墙上小幅遗照出现，不得作为真人出场]。
```

### 示例（父子故事）

```
固定两位主角：父亲约35岁，短黑发，清瘦疲惫的脸，灰蓝色旧工装外套、白色内衫、
深灰长裤、黑布鞋；儿子7岁，圆脸、短黑发、身形小，赭黄色针织上衣、灰蓝长裤、
黑布鞋。两人的脸型、发型、年龄、服装配色和身体比例在所有场景必须一致；
母亲只允许以墙上小幅遗照出现，不得作为真人出场。
```

### Narrative Isolation 规则（必加）

每场 master prompt 末尾必须有这两句：

```
Narrative isolation: the character lock defines identities, not an automatic cast list.
Show only characters explicitly named in the current sentence or strictly required
for its immediate action. Never add family bystanders. Never show a future daughter,
rescued child, grandmother, father or any other supporting character before that
person is introduced by the narration. Do not carry any person, prop or setting
forward merely because it appeared in another scene.
```

**为什么必加**：apiz 会「脑补」前一场出现过的人到下一场，导致叙事穿帮（如父亲回忆时儿子在旁边）。这段约束强制 apiz 只画当前句明确提到的人。

### `--character-lock` CLI 参数

```bash
python gen_story_images.py story.txt \
  --character-lock "固定主角：小红，8岁女孩，圆脸，黑色齐刘海短发，红色棉袄、黑裤子、白球鞋；奶奶，60岁，灰白发盘髻，深蓝对襟褂子、灰裤、黑布鞋。两人比例跨场景一致。"
```

## 三、caption_panel 规范（image2 模式）

> 本节针对**中文 image2**（apiz 中文，顶部字幕带 + 下方方形插画）。英文教学闪卡（`--lang en`）走**两段式但顶部只放句子**：顶部带 y≈0-510 只写英文句子，下方方形插画 y≈512-1536 是彩色插画 + 关键词 IPA 小字叠在插画左下角。ffmpeg 仍在 y≈512 做水平裁切，但切线上方只有纯白底+句子（无 IPA 行），不会被截断。见 `gen_story_images.py` 的 `build_english_flashcard_prompt`。

```
Top copy panel (roughly the top third of the card): pure white background.
Write ONLY this Simplified Chinese caption verbatim, preserving the explicit line breaks:
"<caption text with \n>"
Use thick casual black felt-tip handwriting, one to three lines only, generous
left and right margins, and a large readable letter size. Do not put any illustration
or decorative mark in this top panel. Keep all text in the top panel; do not write
text inside the illustration area below.
```

> ⚠️ **prompt 里不要写像素坐标**（`y=510`、`1024×1024`、`48-pixel`、`10%`）。nano-banana-2 会把这些数字 literally 画到图上（实测卡片边缘出现 `0 / 510 / 512 / 1536 / 8% / 10%`）。用 "top third"、"bottom two-thirds"、"generous margins" 这种相对描述。ffmpeg crop 的像素坐标是后处理，不进 prompt。

**ffmpeg 切分坐标**（仅内部用，不写进 prompt）：
- master 归一化到 1024×1536（portrait）
- y=0–510：字幕区（高度 510px ≈ 33% 总高，可容纳 2-3 行大字）
- y=510–512：白色过渡带（极窄，2px）
- y=512–1536：插画区（1024×1024 正方形）

**为什么不能让 apiz 把字写到插画区**：字幕会被 ffmpeg crop 出来当 text_image 层，如果跑到插画区，crop 会切到插画的一部分。

**为什么字幕区给到 y=510（而不是 22% 标准比例的 y=342）**：nano-banana-2 的中文字号偏大，2 行字幕实际会画到 y=460-500。原来 y=342 的硬限会让第 2 行被切。提到 y=510 给足空间，TextWipe 容器同步加高到 420px。

## 四、illustration_panel 规范

```
Illustration panel (the bottom two-thirds of the card, a square area below the text):
use this area for the scene. Keep the top copy panel completely free of any illustration.
```

`ffmpeg` 的 color 层 crop 公式 `crop=1024:1024:0:512` 对应这个分区，**改一处必须同步改另一处**（gen_story_images.py 的 `split_master_into_layers` 函数）。注意：crop 坐标是代码里的，不要回写进 prompt。

## 五、safe border 硬规则

每场 master prompt 末尾必须有（用相对描述，不要写百分比数字）：

```
Leave a clear white margin around all edges so no visible mark — figure, limb,
prop, building edge, roof, tree branch, rain stroke or motion mark — touches
or crosses a canvas edge. Scale the scene down when necessary and keep generous
white negative space.
```

**为什么**：Remotion 渲染时 `objectFit: 'contain'` 会保持图片完整不裁，但如果原图本身就贴边，contain 后会显得拥挤。safe border 强制 apiz 自己留白。不要写 `10%` / `8%`，模型会把数字画到图上。

## 六、配色约束（蜡笔五色）

```
Color: selective muted wax-crayon color only: sage green, dusty blue, warm tan,
brick red and warm yellow. Keep hair, trousers and other dark areas as black
scribbles. Leave skin and most of the canvas pure white.
```

**五色限定**：
- 鼠尾草绿（sage green）
- 灰蓝（dusty blue）
- 暖棕（warm tan）
- 砖红（brick red）
- 暖黄（warm yellow）

**禁止色**：纯红、纯蓝、亮黄、荧光色、渐变色。这些会让画面失去日记漫画的克制感。

## 七、5 种典型场景示例

### 1. 室内日常

```
Narrative sentence: "他在厨房煮泡面。"
Scene direction: "A tired father standing at a kitchen counter, a pot on a small
gas stove, a packet of instant noodles on the counter, simple line art, sparse props."
```

### 2. 室外活动

```
Narrative sentence: "孩子们在公园里放风筝。"
Scene direction: "Two children running in a park, a kite flying high above,
sparse trees in the background, low horizon line, generous sky negative space."
```

### 3. 情绪特写（不画脸）

```
Narrative sentence: "他偷偷哭了。"
Scene direction: "A man's back from behind, shoulders hunched, head down,
a single small teardrop shape near his cheek area, no face visible, abundant
white negative space around him."
```

⚠️ 手绘日记风的情绪特写**不要画脸**——用背影/侧影/手部动作传达，比正脸特写更克制。

### 4. 时间跳跃（用道具承接）

```
Narrative sentence: "三年后，孩子上学了。"
Scene direction: "A school backpack hanging on a hook by the door, slightly bigger
than the one the child used to have, a small pair of shoes neatly placed underneath.
The father's hand reaches into frame from the right edge only."
```

⚠️ 时间跳跃**用道具变化暗示**，不要直接画"长大的孩子"——观众通过背包大小变化脑补。

### 5. 抽象概念（金句卡）

```
Narrative sentence: "爱是世界上最美味的东西。"
Scene direction: "A simple bowl of noodles in the center, a small heart shape
drawn above the steam, no characters, no other props, abundant white space."
```

## 八、character_reference prompt（00_character_reference.png）

```
Use case: illustration-story
Asset type: fixed protagonist character reference sheet for a hand-drawn Chinese
diary-comic video

Input images: the supplied black-and-white and color frames are style references
only. Ignore their people, composition and Chinese text.

Primary request: draw ONLY the recurring protagonists described below. Show each
protagonist in two simple full-body poses, front view and three-quarter view,
arranged side by side.

Character lock: <你的 character_lock>
Style: <style_lock>
Composition: pure white square canvas, all uncropped full-body poses centered
with generous spacing and a clean white margin around all edges. No scenery,
furniture, extra people, props or decorative marks.

Color: selective muted wax-crayon color only. Follow the clothing colors in the
character lock, use black scribbles for hair and dark trousers, and leave skin
and most of the canvas white.

Constraints: this is an identity reference only; no text, letters, numbers,
labels, captions, speech bubbles, logo, signature or watermark; no realistic
shading, gradients or vector cleanliness.
```

**生成后**：apiz upload 到 CDN，所有后续 master 用 `image_url=<cdn_url>` 引用，nano-banana-2 自动进入图生图模式锁定身份。

## 九、调试 prompt 的方法

### dry-run 看 prompt 不生成图

```bash
python gen_story_images.py examples/story.txt --title "..." --dry-run
```

会打印每场的完整 prompt 到 stdout，并写入 `prompts/<asset_set>/NN_master.txt`。

### 单场重新生成

```bash
# 删掉那场的 master
rm public/assets/generated/<asset_set>/03_master.png

# 重跑（脚本会跳过已存在的，只生成缺失的）
python gen_story_images.py examples/story.txt --title "..."
```

### 全部重新生成

```bash
python gen_story_images.py examples/story.txt --title "..." --force
```

⚠️ `--force` 会重新调 apiz 花钱，确认 prompt 改对了再用。

## 十、常见 prompt 问题排查

| 现象 | 原因 | 修复 |
|---|---|---|
| 主角脸不一样 | 默认纯文生图不保证同一张脸 | 用户明确要求跨场一致才加 `--character-ref` + `--character-lock` |
| 提到父亲时奶奶也在 | narrative isolation 没生效 | 检查 prompt 末尾的 Narrative isolation 段是否完整 |
| 字幕跑到插画区 | caption_panel 相对分区描述错 | 检查 master prompt 里 "top third / bottom two-thirds" 段是否完整，不要写像素坐标 |
| 配色太鲜艳 | style_lock 没强制 | 检查"selective muted wax-crayon only" + 五色限定 |
| 人物头顶出画 | safe border 没生效 | 检查 prompt 末尾"clear white margin around all edges"段是否完整 |
| 画风变精致 | 模型 fallback | 检查 apiz 是否真的用了 nano-banana-2（看 `.last_generate.json`） |
| 画面混入禁止人物（特定种族/性别/时代错位角色/不该有的配角） | 训练先验污染（任何题材都可能） | 见下一节「训练先验污染」，按 v3 玩法重生成 |

## 十一、训练先验污染（必读，任何题材通用）

### 症状

**任何题材**做手绘日记风视频，模型都可能从训练数据强塞不该有的角色。表现：character_lock 写了"绝对禁止 X"，NEGATION suffix 也加上了 "ABSOLUTELY NO X"，但生成图里 X 还是出现，反复重试无效。

这不是某类题材的特殊问题——只要模型训练数据对该题材有强先验就会触发。用户多次实测：家庭/医疗/商务/童话/历史/教育/PPT 步骤都中过。家庭故事塞进宠物，医疗场景默认男医生，商务场景塞白人男老板+亚洲女助理，儿童故事塞迪士尼式公主，全都是同一类问题。

**一个完整案例（mayflower-story）**：五月花号故事 1-10 场只画英国清教徒，但 agnes 见到 "Mayflower/ship/harbor/cabin" 就强联想"感恩节 → 印第安人"，于是在英国清教徒群里塞进铜皮肤辫子羽毛的原住民。两轮 v1/v2 用 NEGATION suffix + PILGRIM_LOCK 强禁，仍泄露 6/10 场。v3 改用正向身份 + CLOSE-UP 才彻底修好。

### 观察过的污染例子（非穷举，任何题材都可能有自己的版本）

| 题材 | 触发词举例 | 模型可能强塞的刻板角色 |
|---|---|---|
| 五月花号/感恩节 | Mayflower, ship, harbor, Pilgrim | Wampanoag 印第安人 |
| 家庭故事 | family, home, parent | 默认白人核心家庭 + 宠物 |
| 医疗场景 | doctor, hospital, surgeon | 男医生（弱化女医生） |
| 商务场景 | CEO, boss, meeting | 白人男老板 + 亚洲女助理 |
| 童话 | princess, castle, prince | 迪士尼式公主（肤色/服饰） |
| 校园/教育 | student, classroom | 特定种族比例 |
| 古风/诗词 | 古风, 诗人, 汉服 | 时代错位的服饰/道具 |

表里只是举例。**遇到污染时不要去对表查"我这是什么题材"——直接按下面 v3 玩法修。**

### v3 玩法（4 个杠杆同时上）

**1. 正向身份压过负向禁止**

NEGATION（"NO Native Americans, NO feathers"）效果弱。**正向锁定**（"ALL figures are pale pink Caucasian English. ALL of them. No exceptions. ALL faces visibly pale pink"）效果强。先告诉模型"画谁"，再说"不画谁"。

```
✗ 弱：ABSOLUTELY NO Native Americans, NO copper skin, NO braids, NO feathers.
✓ 强：ALL figures are pale pink Caucasian English people from 1620 Europe. ALL of them. No exceptions. ALL faces must be visibly pale pink. ALL clothing must be European wool or linen.
```

**2. CLOSE-UP 构图 + 2-3 人上限**

广角人群镜头（4-7 人）给模型太多"塞人"的机会。强制特写：

```
CLOSE-UP portrait composition, ONLY 2 or 3 figures in the frame, no crowd, no group scenes.
```

每场把人物数压到 2-3 个，剩余画布用环境（绳索/桅杆/木墙）填，模型就没有空间塞禁角。

**3. sanitized text：换掉触发词**

prompt 里 `ship/harbor/cabin/Plymouth` 这种题材词全部换掉，破坏先验联想链：

| 触发词 | 换成 |
|---|---|
| ship | wooden deck / wooden interior / vessel |
| harbor | port / shore |
| cabin | small wooden room / dim wooden room |
| Mayflower | (移除，不直接命名船) |
| Plymouth | coastline / new shore |

**visual_plan.json 的 `text` 字段也要重写**，不只是 character_lock——master prompt 是从 `text` 拼出来的，触发词在那里出现一样会污染。

**4. 纯文生图（不用 character_reference）**

`00_character_reference.png` 是用同一个污染 prompt 生成的，本身可能就带禁角。后续 master 用 `image_ref` 引用它，禁角会被 forward 到所有场。

修复时**临时切纯文生图模式**：删 `image_ref`，让每场独立从 PILGRIM_LOCK 重生成身份。一致性会下降，但污染可控。修好后再决定要不要重做 character_reference。

### 验证流程（必做）

修完后**不能裸眼看 master 就放行**——肉眼对单张图会疲劳漏判。流程：

```bash
# 1. 压成 jpg（agnes master 是 PNG，太大）
python -c "
from pathlib import Path
from PIL import Image
for i in range(1, 11):
    src = Path(f'public/assets/generated/<asset>/{i:02d}_master.png')
    if src.exists():
        Image.open(src).convert('RGB').save(f'_check_scene{i:02d}.jpg', quality=85)
"

# 2. Read 工具读 jpg 拿 CDN URL（Windows 反斜杠路径会让 analyze_image 报 400，必须 Read 转链）

# 3. analyze_image MCP 并行调（所有场景同时调，串行太慢）
#    prompt 模板：
#    "Check this image for training-data pollution. Specifically look for [禁忌人物特征].
#     If you see ONLY [正确身份], respond 'CLEAN'. If you see ANY [禁忌人物], respond 'POLLUTED'
#     and describe what you see. Be strict — even one wrong figure means POLLUTED."
```

POLLUTIED 的场次告诉用户，由用户决定：接受现状直接进 preview / 重生成部分场 / 走 v3 完整修复。**不要为了 100% CLEAN 自动卡死 preview 流程**——用户多次实测希望先出片再修。

### 完整修复脚本模板

参考 `<VIDEO_WORKSPACE>/mayflower-story/_fix_pollution_v3.py`。核心结构：

```python
PILGRIM_LOCK_V3 = (
    "CLOSE-UP portrait composition, ONLY 2 or 3 figures in the frame, no crowd.\n\n"
    "ALL figures are pale pink Caucasian English people from 1620 Europe. ALL of them.\n"
    "1. [主角 A]: English man, about 30, pink skin, ...\n"
    "2. [群演 B]: pale pink skin, ...\n\n"
    "[五色配色] \n"
    "ABSOLUTELY FORBIDDEN: [禁忌人物完整特征列表]"
)

SANITIZED_TEXTS = {
    "02": "CLOSE-UP of three pale-skinned English passengers on a wooden deck...",
    "04": "CLOSE-UP at night: a young pale-skinned English sailor in brown wool...",
}

NEGATION = (
    "\n\nHARD CONSTRAINTS: CLOSE-UP shot, 2 or 3 figures MAXIMUM. "
    "ALL figures pale-skinned English in 17th-century European wool. "
    "ABSOLUTELY NO [禁忌]. If you draw [禁忌], the image is rejected."
)

for sid in TARGET:
    base = gsi.build_master_prompt(
        text=SANITIZED_TEXTS[sid],
        caption=scene["text"],
        visual_direction=str(visual_plan.get(sid, "")),
        character_lock=PILGRIM_LOCK_V3,
        text_mode_image2=False,
    )
    prompt = base + NEGATION
    agnes_generate_image(prompt=prompt, out_path=master_path,
                       model=AGNES_DEFAULT_MODEL, size="2K", ratio="2:3")
    # 切三层 + 回写 storyboard
```

### 决策树

```
生成后发现污染？
├─ 1-2 场污染 → 单场重生成（直接调脚本），其余正常进 preview
└─ ≥3 场污染 → 先告诉用户污染情况，三选一：
    A. 接受现状，直接进 preview（用户多次实测优先选这个）
    B. 部分重生成（最多 1-2 轮，避免无止境 fix-loop）
    C. 走 v3 完整修复流程（CLOSE-UP + sanitized text + 去掉 image_ref）

⚠️ **绝对不要自动进入"直到 100% CLEAN 才进 preview"循环**——污染抽检是建议，不是阻塞。
```

### 何时只清洗部分场，不无脑全洗

**故事某些场本就该画"那个看起来像污染的角色"**——比如五月花号故事 11-13 场春到后印第安人 Squanto 出场相助，那时候画面里的原住民是叙事必需，不是污染。**只清洗"不该出现"的场**，叙事正确的场不动。

判断标准：当前的 sentence/caption 是否明确提到了那个角色？提到 = 该画（不洗）；没提到 = 污染（洗）。

### v3 玩法是默认配置，不是少数特例

用户多次实测多个题材都中招，所以**任何项目生完 master 都该跑一遍 analyze_image 抽检**。把抽检当标准流程的一部分，不要等到肉眼发现污染才补救——肉眼对单张图会疲劳漏判，等察觉时往往已经全部都需要重做了。
