"""在正式上传界面前，检查一个视频是否具备圆屏转码所需的基础信息。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from longmemory.infrastructure.media.round_wallpaper import (
    MediaProbeError,
    MediaToolUnavailable,
    probe_round_wallpaper,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="只读探测 SmartRing-Plus 动态壁纸源视频")
    parser.add_argument("source", type=Path, help="本机源视频路径")
    parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe 命令或完整路径")
    args = parser.parse_args()
    try:
        result = probe_round_wallpaper(args.source, ffprobe=args.ffprobe)
    except MediaToolUnavailable:
        print(
            "未找到 ffprobe。请安装 FFmpeg，或通过 --ffprobe 指定 ffprobe.exe 的完整路径。",
            file=sys.stderr,
        )
        return 2
    except MediaProbeError as error:
        print(f"媒体探测失败：{error}", file=sys.stderr)
        return 3
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
