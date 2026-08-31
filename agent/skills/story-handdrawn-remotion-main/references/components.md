# 组件 API 速查

风格锁定文件（**勿改视觉参数**）：`LayerWipe.tsx` / `TextWipe.tsx` / `easing.ts` / `global.css`。
每个新故事只改：`Scene.tsx`（如果需要自定义层挂载顺序）和 `storyboard.json`。

## LayerWipe.tsx — 三层横向揭示原语（核心）

| prop | 类型 | 用途 |
|---|---|---|
| `src` | string | staticFile 路径，如 `'assets/generated/xxx/01_bw.png'` |
| `startFrame` | number | 开始擦除的帧（基于场景内 frame） |
| `durationFrames` | number | 擦除耗时（帧） |
| `opacity` | number? | 默认 1 |
| `zIndex` | number | 层级（text=40 / color=30 / detail=20 / bw=10） |
| `treatment` | `'bw' \| 'detail' \| 'color'` | 决定 CSS filter（grayscale/contrast 配方） |

**实现要点**：
- `clipPath: inset(0 ${100 - progress*100}% 0 0)` 从左到右擦除
- `progress` 走 smoothstep 缓动（`easing.ts` 的 `revealProgress`）
- 容器固定 `left: 74, right: 74, top: 488, bottom: 42`（保证安全边框，给字幕让出 y=50..470 上半区）
- `<Img objectFit="contain">` 绝不裁剪

## TextWipe.tsx — 字幕层

| prop | 类型 | 用途 |
|---|---|---|
| `text` | string | 字幕文字（含 `\n` 换行） |
| `textAsset` | string? \| null | image2 模式给字幕 PNG 路径；不给则用 MaShanZheng 字体直绘 |
| `startFrame` | number | 默认 0（字幕最先出） |
| `durationFrames` | number | 字幕擦除耗时 |

**两种模式**：
1. `textMode='image2'`（默认）：apiz 在 master 上半部画手写体 → ffmpeg 切出 text_image PNG → 这里 `<Img>` 显示
2. `textMode='font'`：用 MaShanZheng 毛笔字体在浏览器里直绘（fallback，质量略差但无需 apiz）

**字体fallback 链**：`OriginalDiaryHand, STKaiti, serif`（@font-face 在 `global.css`）

## Scene.tsx — 单场组装

| 行为 | 说明 |
|---|---|
| `full_uploaded_page` 检测 | 整页上传模式：直接 `<Img objectFit="contain">` 全屏，不切层 |
| 三层组装 | 按 bw → detail → color → text 顺序挂 LayerWipe/TextWipe |
| `narration_audio` 挂载 | 如果 scene 有音频路径，挂 `<Audio src={staticFile(...)} volume={1} />` |
| `at(ratio)` helper | 把 0..1 比例转成场景内绝对帧 |

**修改场景内层级时**：只改 `Scene.tsx` 里的 zIndex 数字，不要改 LayerWipe 内部的 clipPath。

## StoryVideo.tsx — 整片调度

| 组件 | 用途 |
|---|---|
| `CutStoryVideo` | 用 `<Series>` 顺序排场景，硬切 |
| `PageFlipStoryVideo` | 用 `<Sequence>` 重叠排场景，page-flip 转场 |
| `PageFlipScene` | 单场 + 右下角卷页 SVG（clipPath + 渐变 + 投影） |
| `StoryboardVideo` | 根据 `project.transition` 选 cut 或 page-flip |
| `StoryVideo` | 顶层入口，绑定默认 storyboard |

**不要改 PageFlipScene 的 SVG 路径数学**——`xTop` / `xBottom` / `bow` / `foldWidth` 是手算的卷页几何，改一个参数整个翻页效果就崩。

## easing.ts — smoothstep

```typescript
const smoothstep = (v) => v * v * (3 - 2 * v);
export const revealProgress = (frame, startFrame, durationFrames) => {
  const linear = interpolate(frame, [startFrame, startFrame + durationFrames], [0, 1], {clamp});
  return smoothstep(linear);
};
```

**为什么用 smoothstep 不用 ease-in-out**：smoothstep 是 GPU shader 标配，过渡比 CSS ease 更自然，且数学上更可控。

## types.ts — SceneData 完整字段

```typescript
type SceneData = {
  id: string;
  duration_sec: number;
  text: string;                    // 字幕（含 \n）
  narration?: string;              // TTS 原文（含上下文）
  narration_audio?: string | null; // staticFile 路径
  visual: string;
  shot: 'story_beat' | 'full_uploaded_page';
  layers: ('text' | 'bw_full' | 'detail' | 'color')[];
  color_hint: string | null;
  detail_hint: string | null;
  caption_box?: { top: number; height: number } | null;
  assets: {
    text_image?: string | null;
    bw: string | null;
    detail: string | null;
    color: string | null;
  };
};
```

## Root.tsx — 双 Composition

```tsx
<Composition id="PictureSilent" component={StoryVideo} ... />          // 故事文本模式
<Composition id="UploadedPictureSilent" component={UploadedStoryVideo} ... />  // 上传图片模式
```

- `PictureSilent` 读 `storyboard.json`
- `UploadedPictureSilent` 读 `storyboard.uploaded.json`
- 两套独立，互不干扰

**渲染命令**：
- `npm run render` → `out/picture_silent.mp4`（故事文本 + MiniMax 旁白）
- `npm run render:uploaded` → `out/uploaded_picture_silent.mp4`（上传图片 + MiniMax 旁白）

## 哪些文件可改 vs 不可改

| 文件 | 可改？ | 改什么 |
|---|---|---|
| `storyboard.json` | ✅ | 场景列表、duration_sec、narration_audio |
| `src/Scene.tsx` | ⚠️ 谨慎 | 只在需要自定义层顺序或加 Audio 时改 |
| `src/Root.tsx` | ⚠️ 谨慎 | 只在需要加新 Composition 时改 |
| `src/LayerWipe.tsx` | ❌ | 风格锁定 |
| `src/TextWipe.tsx` | ❌ | 风格锁定 |
| `src/StoryVideo.tsx` | ❌ | 卷页几何脆弱，不要碰 |
| `src/easing.ts` | ❌ | 缓动配方 |
| `src/types.ts` | ⚠️ | 只加字段，不改已有字段类型 |
| `src/global.css` | ❌ | @font-face 配方 |
| `remotion.config.ts` | ✅ | 换机器时改 Chrome 路径 |
