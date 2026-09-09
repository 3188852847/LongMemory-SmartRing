"""生成受限圆屏 GIF 样片；只用于真机技术验证，不发布资源分区。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from longmemory.infrastructure.media.round_wallpaper import (
    MediaProbeError,
    MediaToolUnavailable,
    RoundWallpaperTranscodeSpec,
    transcode_round_wallpaper_sample,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 SmartRing-Plus 360×360 GIF 技术验证样片")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--start", type=float, default=60.0)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--fps", type=int, choices=(8, 10, 12), default=10)
    parser.add_argument("--colors", type=int, choices=(64, 96, 128), default=96)
    args = parser.parse_args()
    try:
        result = transcode_round_wallpaper_sample(
            args.source,
            args.destination,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            spec=RoundWallpaperTranscodeSpec(
                start_seconds=args.start,
                duration_seconds=args.duration,
                frame_rate=args.fps,
                colors=args.colors,
            ),
        )
    except MediaToolUnavailable as error:
        print(f"媒体工具不可用：{error}", file=sys.stderr)
        return 2
    except MediaProbeError as error:
        print(f"样片生成失败：{error}", file=sys.stderr)
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
