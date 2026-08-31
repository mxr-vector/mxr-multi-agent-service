---
name: story-handdrawn-remotion
description: 用 Remotion 制作「手绘日记漫画风」故事视频：白底 + 黑色记号笔轮廓 + 蜡笔色，每句故事被画三次（文字→黑白画稿→彩色插画）横向擦除揭示，可选右下角卷页翻书转场，默认 MiniMax 旁白。当用户要把一段中文故事文案、生活日记、儿童绘本、教学小品变成竖屏手绘风视频，或把一组有序的手绘图片变成翻书动画时，必须使用这个 skill。也支持英文教学模式（--lang en）：生成 Oxford 课本风格的教育闪卡图片（句子+关键词音标+插画烧在同一张图上），用于中小学英语教学。触发词：手绘日记视频、日记漫画、故事变视频、手写字幕、擦除揭示、翻书效果、蜡笔色、paper diary comic、手绘故事、3:4 竖屏故事、英文故事、英语教学视频、English story、educational flashcard、英语闪卡。
---

# Story Handdrawn Remotion（手绘日记风故事视频）

把一段中文故事文本（或一组有序的手绘图片）变成 3:4 竖屏（1080×1440）的手绘日记漫画动画。核心方法论：**不是把一张漂亮图配文字朗读，而是把每句故事拆成「文字 → 黑白画稿 → 彩色插画」三阶段横向擦除揭示，让一句话被画出三次。**

这套方法适合任何「生活叙事」类内容：日记、童话、亲情故事、教学小品、产品步骤插画。只要画面能拆成"独立的一句一画"，就能用这套流程制作。

**工具链**：agnes（Agnes Image 2.1 Flash，默认且当前免费，4 路并发生成） / apiz CLI（`fal-ai/nano-banana-2`，付费可选）+ ffmpeg（master 切三层 + caption 自动检测）+ edge-tts（默认免费旁白） / MiniMax T2A v2（高质量可选）+ Remotion（React 控揭示/翻页/渲染）。

**质量原则（70% 即交付）**：单张 master 图达到 70% 标准就直接进下一阶段，不要逐场修污染、不要全量重画、不要写 `_fix_pollution` 脚本。配旁白、字幕、擦除动画后整体观感合格即可。目标是几小时内出片，不是每张图都完美。

**付费图片不许重跑（硬规则）**：apiz nano-banana-2 约 0.32 元/张，16 场≈5 元/轮。**不要**为了"看看 prompt 改了会不会更好"而 `rm -rf public/assets/generated/<hash>/` 重跑，也不要逐张 Read 检查然后重画"稍微不完美"的图。脚本默认 skip 已存在的 master，这是省钱的关键——信任它。改 prompt 模板/代码不会让旧资产重新计费（资产 hash 只取决于 story 文本 + args）。只有某张图**真的无法观看**（全黑/全白/画错主题）才删那一张 `<sid>_master.png` 单跑，其余场次会自动跳过。英文教学（`--lang en`）直接用 `--backend apiz`，别先烧一轮 agnes 试——agnes 画的英文/音标是乱码，不可用。

**默认纯文生图**：`gen_story_images.py` 默认**不生成** character_reference、不使用图生图（实测 character_reference 会被 agnes 当成「角色立绘贴纸」污染每场）。只有用户显式要求角色锁或提供参考图时，才加 `--character-ref`（自动生成 00）或 `--character-ref-image <path>`（用用户提供的图）。

**preview 即成片**：`npm run render:preview`（720×960）产出的 MP4 就是默认交付物。**不要自动跑 `npm run render`（1080×1440）**，除非用户明确说"要高清 / 要 1080p / 要最终版"。1080p 渲染耗时长，preview 在手机/电脑上看已经足够。

**规范样板**：
- `<VIDEO_WORKSPACE>/handdrawn-story-ep01/` — 第一集成品工程（apiz + image2）
- `<VIDEO_WORKSPACE>/yueyanglou-ji/` — agnes + font 模式，免费全流程

遇到排版、节奏、prompt 拿不准的时候，先看它们的 `storyboard.json` 和 `prompts/` 下的 master prompt 留底。

**配套参考**：
- 完整 pipeline（三输入 + 双转场 + 三层切分 + 配音回写）：`references/pipeline.md`
- Remotion 组件 API 速查：`references/components.md`
- apiz nano-banana-2 prompt 配方：`references/prompt-recipes.md`（character_lock + caption_panel + safe border 等硬规则）

## 新一集工作流（11 步）

按以下顺序执行，每步完成再做下一步。

### 1. 读故事 + 列 beat checklist

读用户给的故事文本（粘贴的或 `story.txt` 文件）。先**列 beat checklist**：每段的关键动作、因果转折、道具、笑点、金句、结尾钩子。后续改写时用这张表防止把故事压成提纲。

例：故事「世上最美味的泡面」
- [ ] 单亲爸爸带 7 岁孩子
- [ ] 出差，匆匆关门
- [ ] 路上担心，反复打电话
- [ ] 孩子说"我很好"
- [ ] 提前回家，孩子已睡
- [ ] 发现被子下的泡面 → 怒火
- [ ] 第一次打孩子
- [ ] 孩子解释：给爸爸留的晚餐
- [ ] 真相：另一碗塞被窝保温
- [ ] 抱住孩子，金句

### 2. 写 story.txt（一句一拍，硬规则）

把故事保存为 UTF-8 文本。`gen_story_images.py` 内部的 `splitStory` 会按 `。！？；` 自动切句，超长句按 `，、` 和叙事转折词（后来/然后/突然…）再切。

**硬规则**：
- 单句 ≤ 36 字（softLimit），超长自动切但可能切坏节奏
- 自然段用空行分隔
- 一句一拍 = 一个 master = 一个画面

详见下方「故事忠实度」。

### 3. 视觉规划（可选但强烈推荐）

如果故事里有：
- 时间跳跃（"三年后"、"第二天"）
- 代词指代不明（"他"指的是谁？）
- 医疗场景（打针/手术）
- 年龄敏感角色（孩子长大、老人回忆）
- **任何题材都可能触发训练先验污染**（用户多次实测：家庭/医疗/商务/童话/历史都中过）→ 必读 `references/prompt-recipes.md` 第十一节，预规划 sanitized 文案 + CLOSE-UP 构图

→ 写 `visual_plan.json`，每场指定一个明确的视觉方向：

```json
{
  "01": "A tired father sitting alone at a kitchen table, head in hands, sparse props.",
  "07": "A man's back from behind, hand raised, a child's silhouette cowering, NO face visible on either."
}
```

用法：
```bash
python scripts/gen_story_images.py story.txt --visual-plan visual_plan.json
```

### 4. 脚手架

```bash
mkdir "<VIDEO_WORKSPACE>/<项目名>"
cp -R "./skills/story-handdrawn-remotion/templates/remotion-project/" \
      "<VIDEO_WORKSPACE>/<项目名>/"
cd "<VIDEO_WORKSPACE>/<项目名>" && npm install
```

⚠️ 用原生 `npm install`，不要 `rtk npm install`（rtk 会翻译成 `npm run install` 报错）。

模板自带的目录：
- `public/fonts/` — MaShanZheng 毛笔字体（OFL 协议）
- `public/audio/narration/` — TTS 产出占位
- `public/assets/generated/` — apiz 产出的 master 占位
- `references/style-bw.png` + `style-color.png` — 风格锚点参考图（**必备**，缺了脚本会 hard fail）

### 5. 选输入模式 + 选后端 + 选转场 + 选语言

| 输入 | 命令 |
|---|---|
| 故事文本（默认） | `python scripts/gen_story_images.py examples/story.txt --title "..."` |
| 英文教学故事 | `python scripts/gen_story_images.py examples/story_en.txt --lang en --title "..."` |
| 上传图片 | `node scripts/import_uploaded_pages.mjs --image 01.jpg --image 02.jpg --title "..."` |

语言模式（`--lang`）：
- `zh`（默认）：中文手绘日记漫画风，MaShanZheng 字体字幕，agnes 免费 + font 模式
- `en`：英文教学闪卡风（Oxford 课本风），**两段式**：顶部带只画英文句子，下方插画 + 关键词音标作为小字叠在插画左下角，用于英语教学。详见下方「英文教学模式」

后端选项（`--backend`）：
- `agnes`（默认，Agnes Image 2.1 Flash，当前 $0/张免费，高密度中文手绘风）
- `apiz`（fal-ai/nano-banana-2，付费，老样板用这个）

字幕渲染（`--text-mode`，**未传时按后端自动选**）：
- `agnes` 后端 → 自动用 `font`（MaShanZheng 字体，agnes 不会画中文汉字）
- `apiz` 后端 → 自动用 `image2`（apiz 在画板上画手写体）

转场选项：
- `--transition cut`（默认，硬切）
- `--transition page-flip --transition-sec 0.7`（右下角卷页，0.5–2.0 秒）

### 6. 生成 master + 切三层（gen_story_images.py）

```bash
python scripts/gen_story_images.py examples/story.txt \
  --title "世上最美味的泡面" \
  --visual-plan visual_plan.json \
  --transition cut
# --backend 默认 agnes，--text-mode 默认按后端自动选（agnes→font / apiz→image2）
# 默认纯文生图，不生成 character_reference（避免角色立绘污染）
```

需要角色锁时（用户明确要求或提供了参考图）才加：
```bash
# 自动生成 00_character_reference.png 并走图生图
python scripts/gen_story_images.py story.txt --character-ref
# 或用用户提供的参考图
python scripts/gen_story_images.py story.txt --character-ref-image ./my-ref.png
```

脚本流程：
1. 校验 `references/style-bw.png` + `style-color.png` 存在
2. 分句 + formatCaption + durationFor 估时
3. 默认纯文生图（无 character_reference）；只有加 `--character-ref` / `--character-ref-image` 才生成/使用角色参考
4. **并发**生成 master（默认 4 路，`--concurrency N` 调整；已存在的自动跳过）
5. ffmpeg 切三层：text_image / bw / color（font 模式下 text_image 不切，由 Remotion TextWipe 实时渲染字幕）
6. 写 `storyboard.json`（含 `narration` 字段供 TTS 用）

font 模式下脚本会把中文原句以「要画出的内容、不要写出来」的方式传给模型，避免 agnes 把字幕直接画在图上导致和 Remotion 字幕重叠。

**dry-run 先看 prompt**：
```bash
python scripts/gen_story_images.py examples/story.txt --title "..." --dry-run
```

**切后端到 apiz**（仅当 agnes 不可用或要复用老样板）：
```bash
python scripts/gen_story_images.py examples/story.txt --backend apiz --text-mode image2
```

### 7. 生成旁白（gen_tts.py，默认免费 edge-tts）

`narration.yaml` 从 `storyboard.json` 转换（id + text = narration 字段，**不是 caption 字段**）。**id 必须用 `s01`/`s02` 字符串**（不要用裸数字 `01`，YAML 1.1 会把它当八进制）：

```yaml
voice: zh-CN-XiaoyiNeural   # edge 默认女声；minimax 用 female-shaonv
speed: 1.0
scenes:
  - id: s01
    text: "他是个单亲爸爸，独自带着一个七岁的孩子。"
  - id: s02
    text: "..."
```

跑 edge-tts（默认，免费，无需 API key，需 `pip install edge-tts`）：
```bash
python scripts/gen_tts.py narration.yaml --out-dir public/audio/narration
# voice 自动 zh-CN-XiaoyiNeural（女声）；男声可用 zh-CN-YunxiNeural
```

跑 MiniMax（用户明确要高质量时；apiz speak → 直连 fallback）：
```bash
python scripts/gen_tts.py narration.yaml --backend minimax --out-dir public/audio/narration
```

产出 `s01.mp3 s02.mp3 ...` + `timeline.json`（含 `frames_source` / `frames_playback`）。yaml 用 `sXX` id 时 edge 直接输出 `sXX.mp3`，无需改名脚本。

### 8. 回写 duration_sec（apply_timeline.py）

```bash
python scripts/apply_timeline.py
# 默认用 frames_source（原速）。如需 1.2x 加速：--use-playback
```

会把 `storyboard.json` 每场的 `duration_sec` 改成音频真实时长，同时填 `narration_audio` 字段（让 Scene.tsx 能挂 `<Audio>`）。

### 9. 静态检查（Remotion Studio）

```bash
npm run dev
```

打开 Remotion Studio，重点检查：
- safe border 10% 是否守住（人物头顶/手肘/道具不出边）
- caption 不超 3 行
- character 一致性（同一个人的脸/服装跨场景一致）
- 横向揭示方向一致（text/bw/color 都从左到右）

### 10. 渲染 preview（720×960）= 默认成片

```bash
npm run render:preview
# → out/picture_silent-preview.mp4
```

**⚠️ `picture_silent-preview.mp4` 就是默认交付物**。走完 TTS + apply_timeline 后直接渲 preview，把它交给用户即可。**不要自动跑 1080p 最终渲染**。

只有用户明确说"要高清 / 要 1080p / 要最终版 / 出高清"时才进第 11 步。

### 11.（可选）1080p 高清版 — 仅在用户明确要求时

```bash
npm run render
# → out/picture_silent.mp4

ffprobe -v error -show_streams -show_format out/picture_silent.mp4
```

1080p 渲染 2000+ 帧耗时长，preview 在手机/电脑上看已经足够清晰，不要主动跑。

## 故事忠实度

- 原文是故事，**不是提纲**。改成 video 脚本时可以合并相近句子，但不能删关键桥段导致因果断裂。
- 保留"动作承接"和"道具承接"。开门、转身、拿出物品、合上书这类动作是观众理解下一句的桥。
- 旁白可以压短，但必须保留原文的情绪推进：压力来源 → 冲突 → 误解 → 揭示 → 金句/收尾。
- 单句 ≤ 36 字（`splitStory` 的 softLimit），超长自动切。**故事 txt 不要一句塞两句的内容**。
- 若必须删减，先列出将删的 beat，确认不是后文所需的连接段。
- TTS 前做一次对照：逐场检查 beat checklist，确认没有漏掉重要句子、动作、转折和金句。

## 风格 DNA（不可变）

| 项 | 值 |
|---|---|
| 画布 | 1080×1440 @ 30fps（3:4 竖屏），白底 `#FFFFFF` |
| 揭示 | text → bw → color，三层全部从左到右横向擦除（`inset(0 X% 0 0)`） |
| 转场 | cut 直接切（默认）/ page-flip 右下角卷页 |
| 墨色 | `#171714`，记号笔粗轮廓 + 蜡笔色块 |
| 字幕字体 | 站酷马善政毛笔（MaShanZheng），1.34 行高，-0.35° 倾斜 |
| 五色限定 | 鼠尾草绿 / 灰蓝 / 浅棕 / 砖红 / 暖黄（低饱和蜡笔色，禁止纯红/亮黄/荧光） |
| 素材 | agnes / apiz 生成真实 PNG，**不是**纯代码绘制 |
| 图片生成 | 默认 agnes（`agnes-image-2.1-flash`，免费，ratio 2:3，2K=1664×2496，font 模式归一到 master 1024×1024；image2 模式归一到 1024×1536）；默认 4 路并发生成。可选 apiz（`fal-ai/nano-banana-2`，`image_size='portrait_4_3'`） |
| 字幕渲染 | 默认 font（MaShanZheng 字体，Remotion TextWipe 实时画，图片上不画字） / image2（仅 apiz 支持图片模型画手写体，agnes 不会画中文） |
| 默认配音 | edge-tts，`zh-CN-XiaoyiNeural`（女声，免费，无需 key），`pip install edge-tts` |
| 高质量配音 | MiniMax T2A v2，`female-shaonv`（`--backend minimax`，apiz speak `speech-2.8-hd` → 直连 `speech-02-hd` fallback） |
| 输出 | H.264 MP4，默认含旁白音轨 |
| safe border | 至少 10% 左右、8% 上下，所有笔触不触边 |

> **英文模式（`--lang en`）差异**：风格锁切到 `STYLE_LOCK_EN`（Oxford 课本教育闪卡风，非手绘日记漫画）；字幕模式强制 image2（两段式：顶部带只画句子，关键词+IPA 作为小字叠在下方插画左下角）；配音默认 `en-US-JennyNeural`；估时按词数。详见下方「英文教学模式」。

## 角色一致性（默认关闭）

**默认纯文生图**：不加 `--character-ref`，不生成 `00_character_reference.png`，不传图生图参考。视觉规划靠 `visual_plan.json` 里每句的构图描述 + `--character-lock` 里的服装规则。实测这样出片最快，70% 质量足够。

**需要角色锁时**（用户明确要求同一张脸跨场一致，或提供了参考图）：
```bash
# 自动生成 00 角色锚点
python scripts/gen_story_images.py story.txt --character-ref --character-lock "..."
# 或用用户提供的参考图
python scripts/gen_story_images.py story.txt --character-ref-image ./ref.png
```

`--character-lock` 写服装规则即可（年龄/服装颜色/标志道具），不要写长串负面禁止词——模型会被负面词触发反而画出你禁止的东西。

## 场景语法版式约定

### 1. 标题场景（两种模式）

**image2 模式（中文）**（apiz 后端用，需要图片模型在画板上画手写体字幕）：
- 上半 y=0–510：手写体字幕（apiz 在 master 上画，ffmpeg 切出 text_image 层）
- 下半 y=512–1536：彩色插画（1024×1024 正方形）
- y=510–512：极窄过渡带（2px，实际几乎不可见）
- 字幕区给到 510px 是因为 nano-banana-2 中文字号偏大，2-3 行字幕实际会画到 y=460-500

**image2 模式（英文 `--lang en`）走两段式分区，但顶部带只放句子**：顶部 y≈0-510 切出 text 层（只有英文句子），下方 y≈512-1536 切出 bw/color 方形插画（插画上叠加小字关键词+IPA）。ffmpeg 仍在 y≈512 做水平裁切，但切线上方只有纯白底+句子（没有 IPA 行），不会被截断。详见下方「英文教学模式」。

**font 模式**（agnes 默认，apiz 也可用）：
- 整张 master 1024×1536 全是彩色插画（agnes 不会画中文，所以不在画板上留字幕区）
- 字幕由 Remotion 用 MaShanZheng 毛笔字体实时渲染（`TextWipe` 组件）
- ffmpeg 不切 text_image 层（storyboard 的 `text_image=null`）
- 排版完全可控，不依赖图片模型识字

### 2. 完整页上传（full_uploaded_page）

- `<Img objectFit="contain">` 居中显示原页，绝不裁剪
- 用于 page-flip 模式：保留原页 + 卷页时露出淡化纹理

### 3. 复合页（composite）

- ffmpeg cropdetect 自动找空白带
- 上 caption + 下插画分别切出
- 失败时用 `--split-y 01:320` 手动指定像素行

### 4. 翻书效果（page-flip）

- 每场 Scene 静止显示后，右下角卷起 → 露出下一场
- 纸背保留淡化原页纹理
- 不要叠加 bw/color 阶段（保留原页即可）

### 5. 节奏（durationFor 公式）

```
duration_sec = min(6.2, max(4.4, 3.8 + line_count × 0.48 + char_count × 0.035))
```

- 1 行字幕 ≈ 4.4 秒
- 2 行字幕 ≈ 5.0 秒
- 3 行字幕 ≈ 5.5–6.2 秒
- 配音版会覆盖为真实音频时长

## 节奏（无配音版 + 配音版）

### 无配音版（估时，快速预览排版用）

`gen_story_images.py` 写入 `storyboard.json` 的 `duration_sec` 是估时（公式见上）。用于：
- 第一次跑预览看排版
- 验证场景顺序、转场、字幕布局

**不要停留在无配音版**——`audio.voiceover='pending'` 状态只是中间产物。

### 配音版（默认，必出）

走完 `gen_tts.py` + `apply_timeline.py` 后，`audio.voiceover='active'`，每场 `duration_sec` 是音频真实时长。

### 1.2x 加速（可选，不推荐）

教学/快节奏场景才用：
```bash
python apply_timeline.py --use-playback
# Scene.tsx 的 <Audio> 加 playbackRate={1.2}
```

手绘日记风重韵味，**默认原速**。

## 多音色配音流程（扩展位）

默认单旁白（narration 一个 voice）。如需多音色（旁白 + 角色台词）：

1. 在 narration.yaml 里给 utterance 加 `role` 字段
2. gen_tts.py 暂时按单 voice 处理（可手动改 voice 字段，分多次跑）
3. 未来可扩展支持 role → voice 映射表

详见 `references/pipeline.md` 第五节。

## 音画同步验收

生成配音后，**必须检查**音频、字幕、动画三者对齐：

- 视频总时长 ≈ 音频总时长，不能明显长出或短于
- 每场最后 30 帧不再出现新文字/插画（避免刚出现就切场）
- 抽查每场字幕：`TextWipe` 在 `startFrame=0` 出现，所以字幕一开始就在；插画 `bw` 在 0.18 总时长开始出。**字幕不能比音频晚**——字幕是先于"说到"出现的（视觉铺垫）
- 关键词级抽查：流程词/列表词/金句关键词，必须在音频说到那一句附近出现，不能提前十几帧露后面内容
- 每场最终截图过一次 Subagent 视觉审核：区分"叙事遮挡"vs"穿帮遮挡（人物脸被字盖住）"
- ffprobe 检查 mp4 video/audio duration 一致

详见 `references/pipeline.md` 第五节「配音回写机制」。

## 验收清单（渲染前必过）

技术项（必须过）：
- [ ] **句长合规**：每句 ≤ 36 字（超长会被 `splitLongBeat` 切坏）
- [ ] **caption 不超 3 行**：`formatCaption` 抛错前提前检查
- [ ] **narration_audio 已挂载**：每场 Scene 有 `<Audio>`，`audio.voiceover='active'`
- [ ] **duration_sec 已回写**：用 timeline.json 真实时长，不是估时
- [ ] **ffprobe 检查**：mp4 video/audio duration 一致

质量项（70% 即可，不要逐场修）：
- 故事连贯、字幕不截断、横向揭示方向一致
- 图片有污染/角色重复/构图不完美——**不阻塞出片**，配旁白和动画后整体能看就行
- 只有某张图严重到无法观看（全黑/全白/明显错内容）才重画那一张，不要全量重画

## 静帧查看策略（重要）

`remotion still` 渲出的静帧要肉眼检查排版，但默认放 `out/check-N.png` 在 Windows 下走 analyze_image MCP 会因路径反斜杠报 400。

```bash
# 1. 渲静帧到 out/
npx remotion still PictureSilent --frame=<场景末帧-30> out/check-s1.png

# 2. 缩成 jpg 并复制到 cwd 根目录
python -c "from PIL import Image; Image.open('out/check-s1.png').convert('RGB').save('_verify-s1.jpg', quality=85)"

# 3. Read 工具读 _verify-s1.jpg，拿到干净的 CDN URL 再传给 analyze_image
```

## 常见坑

- **rtk npm install 会失败**，用原生 `npm install`。
- **references/style-bw.png / style-color.png 缺失** → `gen_story_images.py` 启动时 hard fail。模板自带这两张图，不要删。
- **`--no-character-ref` 滥用** → 主角每场长出不同的脸。除非测试 prompt，否则永远不要用。
- **caption 超 3 行** → `formatCaption` 抛错。预先在 story.txt 把长句拆开（≤36 字）。
- **Chrome Headless Shell 国内下载卡**（113MB storage.googleapis.com）→ 模板的 `remotion.config.ts` 已配 Windows Chrome 路径，跳过下载。换机器若 Chrome 路径不同，改这个配置。
- **`--transition page-flip` 的 master 必须完整未裁剪** → 卷页会露出原页纹理，被裁过会穿帮。
- **复合页 cropdetect 失败** → 用 `--split-y 01:320` 手动指定 caption 与插画的分界像素行。
- **nano-banana-2 不支持 portrait_4_3** → fallback 到 `square_hd` + ffmpeg pad。`gen_story_images.py` 已用 portrait_4_3，若 apiz 报错，改 `image_size` 参数。
- **不要停留在无配音估时版**（`audio.voiceover='pending'`）——真实 TTS 生成后必须 `apply_timeline.py` 回写一版。
- **不要因为追求短而删故事连接段**——场数可增加（10→12→15），连贯性优先。
- **apiz 余额不足** → 脚本启动时会自动 `apiz account balance --json` 预检（<10 元直接退出，不烧一轮 429）。也可手动 `apiz account balance` 查。图片生成失败无法 fallback（不像 TTS 有直连兜底），需充值或换 agnes（仅限中文）。
- **并发静默失败（已修）** → 旧版 `list(as_completed([...]))` 从不调 `.result()`，apiz 429/网络错时 16 个线程全抛异常但主流程假装成功，继续写空 storyboard。已改成 try/except 收集失败场次并 `SystemExit`，且生成后校验文件 >1KB。改并发逻辑时务必保留 `.result()` 调用和文件校验。
- **prompt 里写像素坐标/百分比会被画到图上** → nano-banana-2 会把 prompt 里的 `y=510`、`1024×1024`、`10%`、`48-pixel` 当文字 literally 画在卡片边缘。所有生图 prompt 必须用相对描述（"top third"、"bottom two-thirds"、"generous margins"），不能给数字坐标。改 prompt 模板时别重新引入。
- **要高质量配音** → `gen_tts.py --backend minimax`（默认是免费 edge-tts）。
- **音频混合失败（audio-mixing 目录缺失）** → 根因是并发渲染竞争 Windows temp。模板已设 `Config.setConcurrency(1)`。⚠️ **绝对不要同时跑多个 `remotion render`**。
- **第 2 行字幕被切** → 历史 bug：原来 `CAPTION_CROP_HEIGHT=342` 太小，nano-banana-2 中文字号偏大实际画到 y=460-500。已修：crop 高度 342→510、scale 1536:765、TextWipe 容器 height 288→420 / top 86→50、LayerWipe top 382→488。**4 处必须同步改**（`gen_story_images.py` 的 CAPTION_CROP_HEIGHT + scale + TextWipe.tsx 容器 + LayerWipe.tsx 容器）。如果只动 crop 不动容器，文字会被压扁。
- **agnes 不会画中文 / font 模式把字幕画进图** → agnes 后端必须用 `--text-mode font`（默认）。font 模式下脚本在有 `--visual-plan` 时**不把中文原句放进 prompt**（只给英文 scene direction），避免 agnes 把旁白当字幕画在图上和 Remotion TextWipe 重叠。没有 visual_plan 时才把中文以「要画出、不要写出来」的方式传入。显式传 `--backend agnes --text-mode image2` 会踩坑（agnes 把整版画满）。
- **agnes 上游 503/500/网络超时** → `lib_agnes.py` 自带 4 次指数退避（5/10/20/40s，重试 500/502/503/504）。脚本对每场 master 自动 skip 已存在的，可反复重跑直到全部完成。
- **Windows GBK subprocess UnicodeDecodeError** → 含中文路径下 ffmpeg stderr 被 Python 默认按 GBK 解码炸掉。脚本所有 subprocess.run 已加 `encoding="utf-8", errors="replace"`。改脚本时新加 subprocess 也要带。
- **edge-tts 文件名** → `narration.yaml` 的 id 一律用 `s01`/`s02` 字符串（不要用裸数字 `1`/`01`，YAML 1.1 会把 `01` 当八进制 int），这样 edge 直接输出 `s01.mp3`，timeline id 也是 string，`apply_timeline.py` 直接匹配、并把路径归一化成 `audio/narration/sXX.mp3`（无需 `_fix_audio` 脚本）。
- **agnes master 尺寸** → agnes 2:3 @ 2K = 1664×2496；font 模式 `_normalize_master` 缩到 1024×1024，image2 模式缩到 1024×1536（脚本已自带，改 ratio 才需重算）。
- **训练先验污染（非阻塞）** → agnes/apiz **任何题材**都可能强塞刻板角色。默认纯文生图 + visual_plan 的 CLOSE-UP/背影视角构图已大幅缓解。**按 70% 原则不阻塞出片**：发现污染告诉用户即可，只有某张严重到无法观看（全黑/全白/错内容）才单独重画那一张，不要全量重画、不要写 `_fix_pollution_v3` 脚本。
- **图片生成慢** → 默认 4 路并发（`--concurrency N`），15 张约 2-3 分钟。已存在的 master 自动跳过；改文案只影响对应场次，删那一张 master 重跑即可，不要全量重生成。
- **agnes HTTP 500 也要重试** → `lib_agnes.py` 已扩展重试白名单到 `(500, 502, 503, 504)`（之前只重试 502-504）。500 通常是上游 `do_request_failed` 瞬时错，5s 后重试就好。

## 适用范围

这套方法适合任何「一句一画」的叙事：

- 日记漫画 / 生活记录
- 童话 / 儿童绘本
- 亲情 / 情感故事
- 教学小品（步骤插画）
- 产品步骤演示（不重实物，重氛围）

**不适合**：
- 实物产品展示（用 product-launch-video）
- 真人/口播视频（用 talking-head-remotion）
- 微信公众号文章转视频（用 wechat-article-remotion）
- 纸片分层动画（用 paper-cutout-remotion）
- 数学/几何证明（用 geometry-math-proof-remotion）

真正让手绘日记风有韵味的，不是单张图多漂亮，而是「一句话被画出三次」的节奏 + 「文字先于声音出现」的视觉铺垫。

## 英文教学模式（`--lang en`，英语教学专用）

当用户要**做英文故事用于英语教学**时，加 `--lang en`。此模式下所有文案、图片生成、旁白都按英文，生图风格从「手绘日记漫画」切换到「Oxford 英语课本教育闪卡」。

### 核心区别

| 项 | `--lang zh`（默认） | `--lang en` |
|---|---|---|
| 风格 | 手绘日记漫画（蜡笔色 + 记号笔轮廓） | Oxford 英语课本闪卡（清爽教育插画风） |
| 图片内容 | 纯插画（字幕由 Remotion 渲染） | **两段式：顶部只有句子，下方插画 + 关键词音标小字叠在插画左下角** |
| 字幕模式 | font（MaShanZheng，agnes 不画中文） | image2（顶部句子切独立 text 层，下方插画切 bw/color） |
| 关键词 | 无 | 每句自动提取 2-4 个重点词汇，带 IPA 音标（叠在插画上） |
| 旁白语音 | `zh-CN-XiaoyiNeural` | `en-US-JennyNeural` |
| 估时公式 | 按字数 | 按词数（英文朗读更慢，时间更长） |

### 两段式布局（重点）

英文闪卡仍然是**上下两段**，但顶部带的「字幕」只有句子本身，**关键词和 IPA 音标不再画在顶部带**——它们作为**小字体叠在下方插画的左下角**：

```
┌─────────────────────────┐
│  Sentence at top        │ ← 顶部带：只有英文句子（大字）
│  (large black font)     │
├─────────────────────────┤
│                         │
│       illustration      │ ← 下方方形插画
│                         │
│  keyword1 /kənˈtest/    │ ← 关键词+IPA：小字叠在插画左下角
│  keyword2 /ˈneɪbl/      │
└─────────────────────────┘
```

**为什么这样布局**：
- 顶部带只放句子 → ffmpeg 在 y≈512 水平裁切时，切线上方是纯白底+英文字符，没有 IPA 行会被截断
- IPA 作为小标注叠在插画左下角 → 不抢插画主体的视觉重量，但学生仍能看到发音
- 顶部句子带由 Remotion TextWipe 第 0 帧揭示 → 每场开头立即显示句子，不会全白等待

**给 apiz/nano-banana-2 的 prompt 关键约束**（见 `gen_story_images.py` 的 `build_english_flashcard_prompt`）：
- 顶部带：ONLY 句子，NO keywords，NO phonetics
- 下方方形插画：用插画填满
- 关键词+IPA：作为 SMALL labels 叠在插画左下角，左对齐竖排堆叠，clearly secondary to the picture
- 插画左下角保持干净明亮（天空/墙壁/白纸）以保证小音标可读
- 不要画水平分隔线、面板边框
- 不要在 prompt 里写像素坐标（`y=510`）或百分比（`10%`）—— nano-banana-2 会把这些数字 literally 画到图上

### 后端选择（两个都可以，按预算和质量要求挑）

- **`--backend apiz`（推荐）**：nano-banana-2 文字渲染更稳，句子+IPA 拼写正确率更高。付费（约 0.32 元/张，16 场≈5 元）。
- `--backend agnes`（默认，免费）：agnes + image2 有已知问题——可能把插画范围画得太大覆盖句子带，英文/音标也可能拼错（实测出现过 `keywiods`、`compfur-cartan` 这类乱码）。脚本能跑通，**接受 70% 文字质量即可，不要逐张修**；如果对教学可读性要求高，换 apiz。

```bash
# 推荐：apiz 后端，文字渲染最稳
python scripts/gen_story_images.py examples/story_en.txt --lang en --backend apiz --title "English Story"

# 免费：agnes 后端（文字可能不完美，70% 即可）
python scripts/gen_story_images.py examples/story_en.txt --lang en --title "English Story"

# dry-run 先看 prompt（不烧钱）
python scripts/gen_story_images.py examples/story_en.txt --lang en --dry-run
```

> nano-banana-2 有时返回 416×624 的小图，脚本会自动 lanczos 放大到 1024×1536。画面会偏软但完全可用——不要为此换更贵的模型或重跑，70% 原则。

### 英文故事写作规范

- 一句一拍，英文按 `. ! ? ;` 切句（中文按 `。！？；`）
- 单句 ≤ 120 字符（softLimit），超长按逗号/连接词切
- 自然段用空行分隔
- 每句配一张闪卡 = 一个画面

### TTS 配音

narration.yaml 加 `lang: en`，voice 自动切英文：

```yaml
lang: en
voice: en-US-JennyNeural   # edge 默认女声；男声用 en-US-GuyNeural
speed: 0.95                 # 教学可稍慢
scenes:
  - id: s01
    text: "The little rabbit hopped through the green meadow."
  - id: s02
    text: "..."
```

### 三层揭示的教学意义

英文闪卡仍然走「文字 → 黑白 → 彩色」三阶段横向擦除，和中文模式对齐：
1. **文字层**（text_image，顶部句子带）：第 0 帧揭示 → 学生先看到完整句子，可以跟读
2. **黑白层**（bw，下方方形插画）：从左到右擦入线稿 + 插画左下角的关键词音标 → 学发音、理解词义
3. **彩色层**（color）：从左到右擦入完整彩色插画 → 视觉记忆

顶部句子带在第 0 帧出现，所以每场开头立即显示句子，**不会全白等待**——这是把音标从顶部带挪到插画上的关键收益。

### 常见坑（英文模式）

- **agnes + image2 文字质量不稳定** → agnes 可能把插画范围画得太大挤掉顶部句子带，英文/音标也可能拼错（`keywiods`、`compfur-cartan`）。对教学可读性要求高就用 `--backend apiz`；能接受 70% 就用免费 agnes 直接出片，不要逐张修。
- **Quiz/Answer 闪卡要手动清空关键词** → `extract_keywords()` 会从 "Quiz: Who did AlphaGo beat?" 里抽出 `Quiz / AlphaGo / beat` 这种没教学意义的词。在 `visual_plan.json` 里给问句和答句场次显式设 `"keywords": []`。
- **IPA 音标渲染** → nano-banana-2 对大部分 IPA 符号渲染清楚，个别符号可能不完美。按 70% 原则接受；只有严重到看不懂才在 `visual_plan.json` 里把该场 `"keywords": []` 只留句子。
- **英文分句切太碎** → `split_story_en` 按 `. ! ? ;` 切，超长句按逗号/连接词再切。如切坏节奏，手动在 story.txt 里调整句号位置。
- **估时太长** → `duration_for_en` 按词数给时间（英文比中文慢）。配音后 `apply_timeline.py` 会用音频真实时长覆盖估时。
