# Pipeline 详解（三种输入 + 双转场 + 三层切分 + 配音回写）

> 本文档是 SKILL.md「新一集工作流」的展开参考。SKILL.md 给出步骤顺序，本文档解释每一步内部的机制。

## 一、三种输入模式

### 1. 故事文本（默认，最常用）

```bash
python scripts/gen_story_images.py examples/story.txt --title "纸上的夏天"
```

- 输入：UTF-8 文本，自然段用空行分隔，每段一句话或多句
- 内部分句算法：见下方「分句算法」
- 产出：每句一个 master + 切三层 + storyboard.json

### 2. 上传图片（用户已有手绘图片）

```bash
node scripts/import_uploaded_pages.mjs \
  --image /absolute/01.jpg --image /absolute/02.jpg \
  --title "我的故事"
```

- 输入：JPG/PNG 列表（按播放顺序）
- 自动检测每张图是否是「复合页」（上半 caption + 下半插画）
  - 是 → ffmpeg 自动 cropdetect 找空白带，切成 caption + art
  - 否 → 整图作为 color 层
- 不走 apiz（用户已有图，纯 ffmpeg 切层）
- 适合：把纸质手账/绘本扫描件变成视频

### 3. 混合（极少用）

不支持混合输入。要么全用故事文本生成，要么全用上传图片。如果要混合，分两次跑生成不同的 storyboard，再手工合并。

## 二、双转场

### cut（默认，直接切）

每场独立播放，最后 0 帧直接切到下一场第 0 帧。适合短促、生活化的故事节奏。

```bash
python scripts/gen_story_images.py examples/story.txt --transition cut
```

视觉：场景之间有断点感，每场自成一体。

### page-flip（右下角卷页）

下一场开始前，从右下角卷起当前页，露出下一页。卷页时纸背保留淡化原页纹理。

```bash
python scripts/gen_story_images.py examples/story.txt --transition page-flip --transition-sec 0.7
```

- `--transition-sec`：卷页耗时（0.5–2.0 秒，默认 0.7）
- 实现：见 `src/StoryVideo.tsx` 的 `PageFlipScene`（SVG clipPath + 渐变 + 投影）
- 适合：完整绘本/日记翻页感的故事

⚠️ **page-flip 模式 master 必须完整未裁剪**——卷页会露出原页纹理，被裁过会穿帮。

## 三、三层切分原理

每场画面被切成 3 个 PNG，按从后到前的顺序叠加渲染：

| 层 | zIndex | 内容 | 渲染时机 |
|---|---|---|---|
| text_image | 40 | 手写体字幕（image2 模式才有） | 第 0 帧 |
| bw | 10 | 黑白画稿（grayscale + contrast） | 0.18 总时长 |
| color | 30 | 彩色插画 | 0.52–0.65 总时长 |

### 横向揭示（一致方向）

三层都用 `clipPath: inset(0 ${100 - progress*100}% 0 0)` 从左到右擦除。
**为什么保持一致方向**：避免不同层切换时画面「跳」，让观众感觉是一笔画出的。

### 切层公式（ffmpeg filter）

```bash
# text_image（仅 image2 模式）
ffmpeg -i master.png -vf \
  "crop=1024:510:0:<caption_y>,scale=1536:765:flags=lanczos" text.png

# bw
ffmpeg -i master.png -vf \
  "crop=1024:1024:0:512,format=gray,eq=contrast=1.18:brightness=0.035,unsharp=5:5:0.55:5:5:0" bw.png

# color
ffmpeg -i master.png -vf "crop=1024:1024:0:512" color.png
```

`<caption_y>` 由 ffmpeg cropdetect 自动检测（master 上半部分字幕区域的垂直偏移），失败时返回 0（top-aligned）。

## 四、分句算法（splitStory / splitLongBeat / formatCaption）

### 输入约束

- 单句 ≤ 36 字（`softLimit`），超长自动切
- 切句优先级：`。` > `！？` > `；` > `，、` > 叙事转折词（后来、然后、突然…）
- 自然段用空行分隔

### formatCaption

每句重新格式化为字幕（≤3 行，每行 ≤13 字）：
- 在 `，、；：` 处优先换行
- 找不到合适标点时按字数硬切
- 超 3 行会抛错（`splitLongBeat` 已经把长句切短，但仍可能因 caption 排版超 3 行）

### durationFor

```python
duration = min(6.2, max(4.4, 3.8 + line_count * 0.48 + char_count * 0.035))
```

- 1 行字幕：~4.4 秒
- 2 行字幕：~5.0 秒
- 3 行字幕：~5.5–6.2 秒
- 配音版会覆盖为真实音频时长

## 五、配音回写机制（timeline.json → storyboard.json）

### 流程

```
gen_story_images.py  →  storyboard.json  (audio.voiceover=pending, duration_sec=估时)
                                  ↓
narration.yaml       ←  手写或从 storyboard.json 转换（id+text=narration 字段）
                                  ↓
gen_tts.py           →  public/audio/narration/sNN.mp3 + timeline.json
                                  ↓
apply_timeline.py    →  storyboard.json  (audio.voiceover=active, duration_sec=真实时长, narration_audio=路径)
                                  ↓
npm run render:preview  →  out/picture_silent-preview.mp4 (含 MiniMax 旁白)
```

### timeline.json 字段

```json
[
  {
    "id": "s01",
    "file": "audio/narration/s01.mp3",
    "text": "他是个单亲爸爸...",
    "seconds": 6.42,
    "frames_source": 208,      // 原速帧数 = ceil(秒×30)+15
    "frames_playback": 174     // 1.2x 加速帧数 = ceil(source/1.2)
  }
]
```

### 默认原速 vs 1.2x 加速

`apply_timeline.py` 默认用 `frames_source`（原速）。手绘日记风重韵味，**不建议 1.2x 加速**。

如需 1.2x（教学/快节奏）：
```bash
python apply_timeline.py --use-playback
# 同时 Scene.tsx 的 Audio 加 playbackRate={1.2}
```

## 六、character 一致性的 apiz 链路

### 流程

```
gen_story_images.py 启动
       ↓
[Step 1] 生成 00_character_reference.png
       - prompt: character_lock（年龄/发型/服装/比例）+ style_lock
       - apiz generate --image-size square_hd
       ↓
[Step 2] apiz upload → 拿到 CDN URL
       - 后续所有 master 都用 --image-url 引用这张图
       - nano-banana-2 进入图生图模式，锁定人物身份
       ↓
[Step 3] 每句生成 master
       - apiz generate --image-url <char_ref_url>
       - 主角的脸/服装/比例跨场景一致
```

### 跳过 character_reference（不推荐）

```bash
python gen_story_images.py story.txt --no-character-ref
```

后果：每场独立生成，主角可能长出不同的脸/衣服。只在「单主角单场景」或「测试 prompt」时用。

## 七、文件命名规范

```
public/assets/generated/<safe_title>-<8 字符 hash>/
├── 00_character_reference.png    # 角色参考图（character_lock）
├── 01_master.png                  # 第 1 场 master（apiz 原始产出）
├── 01_text.png                    # 第 1 场字幕层（image2 模式）
├── 01_bw.png                      # 第 1 场黑白画稿
├── 01_color.png                   # 第 1 场彩色插画
├── 02_master.png ... 03_master.png ...
└── ...

prompts/<safe_title>-<hash>/
├── 00_character_reference.txt     # 角色参考图 prompt（留底）
├── 01_master.txt                  # 第 1 场 master prompt（留底）
└── ...

public/audio/narration/
├── s01.mp3 s02.mp3 ...            # 每场一个 mp3
└── timeline.json                  # 时长 + 帧数表
```

`<hash>` = sha256(title + text_mode + transition + character_lock + 故事文本) 前 8 字符，保证不同故事的资产不冲突。

## 八、storyboard.json schema 完整说明

```typescript
type Storyboard = {
  project: {
    title: string
    width: 1080, height: 1440, fps: 30, ratio: '3:4'
    transition: 'cut' | 'page-flip'
    transition_sec: number  // 仅 page-flip 用
    style_lock: string      // 视觉风格锁
    character_lock: string  // 角色一致性约束
    audio: {
      voiceover: 'pending' | 'active' | 'post'
      default_backend: 'minimax' | 'edge'
      bgm: 'optional_bed_only'
    }
  }
  scenes: Array<{
    id: string                  // '01' '02' ...
    duration_sec: number        // 单场时长（apply_timeline 回写）
    text: string                // 字幕文字（含 \n）
    narration: string           // TTS 朗读原文（比 caption 长）
    narration_audio?: string    // staticFile 路径 'audio/narration/s01.mp3'
    layers: ('text'|'bw_full'|'detail'|'color')[]
    assets: {
      text_image?: string
      bw: string
      detail: null
      color: string
    }
  }>
}
```

`narration` 字段是 TTS 的文本源——它**不是字幕原文**，而是含上下文的扩展版（给配音演员更多语气信息）。`gen_tts.py` 的 narration.yaml 应该用 `narration` 字段而不是 `text` 字段。
