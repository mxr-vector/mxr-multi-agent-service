"""apply_timeline.py — 把 gen_tts 产出的 timeline.json 回写 storyboard.json 的 duration_sec

gen_tts.py 跑完后会在 public/audio/narration/timeline.json 写入每段音频的真实时长。
这个脚本读 timeline，把 storyboard.json 每场的 duration_sec 改成 frames_source / 30
（原速播放，对齐手绘日记风的韵味节奏；如需 1.2x 交付，用 frames_playback）。

用法：
  python apply_timeline.py                          # 默认路径
  python apply_timeline.py --timeline public/audio/narration/timeline.json \\
                           --storyboard storyboard.json
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

FPS = 30


def main():
    parser = argparse.ArgumentParser(
        description="把 timeline.json 的 frames 回写 storyboard.json 的 duration_sec",
    )
    parser.add_argument(
        "--timeline", default="public/audio/narration/timeline.json",
        help="gen_tts.py 产出的 timeline.json 路径",
    )
    parser.add_argument(
        "--storyboard", default="storyboard.json",
        help="目标 storyboard.json 路径（in-place 修改）",
    )
    parser.add_argument(
        "--use-playback", action="store_true",
        help="用 frames_playback（1.2x 加速）而非 frames_source（原速）。默认原速。",
    )
    args = parser.parse_args()

    timeline_path = Path(args.timeline)
    storyboard_path = Path(args.storyboard)

    if not timeline_path.exists():
        raise SystemExit(f"timeline.json 不存在: {timeline_path}（先跑 gen_tts.py）")
    if not storyboard_path.exists():
        raise SystemExit(f"storyboard.json 不存在: {storyboard_path}")

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    sb = json.loads(storyboard_path.read_text(encoding="utf-8"))

    # timeline 的 id 是 "s01" / "s02"，storyboard 的 scene id 是 "01" / "02"
    # 都做归一化（去 s 前缀）匹配
    tl_map = {}
    for item in timeline:
        sid = str(item["id"]).lstrip("s").lstrip("S")
        tl_map[sid] = item

    field = "frames_playback" if args.use_playback else "frames_source"

    updated = 0
    for scene in sb.get("scenes", []):
        sid = str(scene["id"])
        if sid not in tl_map:
            print(f"  ⚠️ 场景 {sid} 在 timeline 里找不到，跳过（保留原 duration_sec={scene.get('duration_sec')}）")
            continue
        frames = tl_map[sid][field]
        old_dur = scene.get("duration_sec")
        new_dur = round(frames / FPS, 2)
        scene["duration_sec"] = new_dur
        # 同步把 narration_audio 路径写进去（让 Scene.tsx 能挂 <Audio>）。
        # timeline.file 在 Windows 上可能是 public\audio\narration\s01.mp3，
        # 统一成正斜杠并去掉 public/ 前缀，得到 Remotion staticFile 期望的
        # "audio/narration/s01.mp3"（相对 public/，无前导斜杠）。
        audio_rel = tl_map[sid].get("file", "").replace("\\", "/")
        if audio_rel.startswith("public/"):
            audio_rel = audio_rel[len("public/"):]
        audio_rel = audio_rel.lstrip("/")
        scene["narration_audio"] = audio_rel
        print(f"  场景 {sid}: {old_dur}s → {new_dur}s (frames={frames}, {field}) audio={audio_rel}")
        updated += 1

    # 标记 audio.voiceover 已激活
    sb.setdefault("project", {}).setdefault("audio", {})["voiceover"] = "active"

    storyboard_path.write_text(
        json.dumps(sb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n✓ 回写 {updated}/{len(sb.get('scenes', []))} 场 → {storyboard_path}")
    print(f"  使用字段：{field}")
    if not args.use_playback:
        print("  （原速播放。如需 1.2x 加速节奏，加 --use-playback）")


if __name__ == "__main__":
    main()
