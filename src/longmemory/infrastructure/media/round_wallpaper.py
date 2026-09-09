"""圆屏动态壁纸的只读媒体探测。

原始视频属于用户本机素材，不能依靠扩展名猜测格式。这里把 ``ffprobe`` 隔离在
基础设施边界，先获得可审计的编码、尺寸、时长和音轨信息；后续转码和控制台都
消费这个稳定结果，不把外部工具输出直接扩散到业务层。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
from typing import Any


class MediaToolUnavailable(RuntimeError):
    """当前环境找不到媒体探测工具。"""


class MediaProbeError(RuntimeError):
    """工具存在，但输入不是当前可识别的视频或探测失败。"""


@dataclass(frozen=True)
class RoundWallpaperProbe:
    """后续转码决策所需的最小、与 ffprobe 原始 JSON 解耦的事实。"""

    file_name: str
    size_bytes: int
    container: str
    duration_seconds: float
    video_codec: str
    width: int
    height: int
    frame_rate: float
    has_audio: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _positive_number(value: object, code: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise MediaProbeError(code) from error
    if number <= 0:
        raise MediaProbeError(code)
    return number


def _frame_rate(value: object) -> float:
    if not isinstance(value, str) or not value:
        raise MediaProbeError("invalid_video_frame_rate")
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return _positive_number(value, "invalid_video_frame_rate")
    divisor = _positive_number(denominator, "invalid_video_frame_rate")
    return _positive_number(numerator, "invalid_video_frame_rate") / divisor


def _parse_probe(payload: object, source: Path) -> RoundWallpaperProbe:
    if not isinstance(payload, dict):
        raise MediaProbeError("invalid_probe_result")
    streams = payload.get("streams")
    format_info = payload.get("format")
    if not isinstance(streams, list) or not isinstance(format_info, dict):
        raise MediaProbeError("invalid_probe_result")

    videos = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    if len(videos) != 1:
        raise MediaProbeError("expected_one_video_stream")
    video = videos[0]
    codec = video.get("codec_name")
    container = format_info.get("format_name")
    if not isinstance(codec, str) or not codec or not isinstance(container, str) or not container:
        raise MediaProbeError("invalid_video_format")

    width = video.get("width")
    height = video.get("height")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise MediaProbeError("invalid_video_dimensions")

    reported_size = format_info.get("size")
    size = int(_positive_number(reported_size, "invalid_video_size")) if reported_size is not None else source.stat().st_size
    return RoundWallpaperProbe(
        file_name=source.name,
        size_bytes=size,
        container=container,
        duration_seconds=round(_positive_number(format_info.get("duration"), "invalid_video_duration"), 3),
        video_codec=codec,
        width=width,
        height=height,
        frame_rate=round(_frame_rate(video.get("avg_frame_rate")), 3),
        has_audio=any(
            isinstance(stream, dict) and stream.get("codec_type") == "audio"
            for stream in streams
        ),
    )


def probe_round_wallpaper(
    source: Path,
    *,
    ffprobe: str = "ffprobe",
    timeout_seconds: float = 30.0,
) -> RoundWallpaperProbe:
    """只读探测一个本机视频，不复制素材，也不信任文件扩展名。"""

    source = Path(source).resolve()
    if not source.is_file():
        raise MediaProbeError("wallpaper_source_not_found")
    command = [
        ffprobe,
        "-v", "error",
        "-show_entries",
        "format=duration,size,format_name:stream=codec_type,codec_name,width,height,avg_frame_rate",
        "-of", "json",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except (FileNotFoundError, PermissionError) as error:
        # Windows 可能为同名应用执行别名返回拒绝访问；对产品而言仍是当前工具不可执行。
        raise MediaToolUnavailable("ffprobe_not_found") from error
    except subprocess.TimeoutExpired as error:
        raise MediaProbeError("ffprobe_timeout") from error

    if completed.returncode != 0:
        raise MediaProbeError("ffprobe_failed")
    try:
        payload: Any = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MediaProbeError("invalid_probe_json") from error
    return _parse_probe(payload, source)
