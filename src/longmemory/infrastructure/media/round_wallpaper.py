"""圆屏动态壁纸的只读媒体探测。

原始视频属于用户本机素材，不能依靠扩展名猜测格式。这里把 ``ffprobe`` 隔离在
基础设施边界，先获得可审计的编码、尺寸、时长和音轨信息；后续转码和控制台都
消费这个稳定结果，不把外部工具输出直接扩散到业务层。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
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


@dataclass(frozen=True)
class RoundWallpaperTranscodeSpec:
    """受限的技术验证参数，避免把自由 FFmpeg 参数暴露给控制台。"""

    start_seconds: float = 60.0
    duration_seconds: float = 5.0
    frame_rate: int = 10
    colors: int = 96

    def validate(self) -> None:
        if not 0 <= self.start_seconds <= 86_400:
            raise MediaProbeError("invalid_wallpaper_start")
        if not 3 <= self.duration_seconds <= 5:
            raise MediaProbeError("invalid_wallpaper_duration")
        if self.frame_rate not in {8, 10, 12}:
            raise MediaProbeError("invalid_wallpaper_frame_rate")
        if self.colors not in {64, 96, 128}:
            raise MediaProbeError("invalid_wallpaper_colors")


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


def transcode_round_wallpaper_sample(
    source: Path,
    destination: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    spec: RoundWallpaperTranscodeSpec | None = None,
    max_output_bytes: int = 4 * 1024 * 1024,
    timeout_seconds: float = 120.0,
) -> dict[str, object]:
    """原子生成技术验证 GIF，并用独立探测结果核对输出契约。"""

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise MediaProbeError("wallpaper_source_not_found")
    if destination.suffix.lower() != ".gif":
        raise MediaProbeError("wallpaper_destination_must_be_gif")
    if type(max_output_bytes) is not int or max_output_bytes <= 0:
        raise MediaProbeError("invalid_wallpaper_size_budget")
    spec = spec or RoundWallpaperTranscodeSpec()
    spec.validate()

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{os.getpid()}.tmp.gif")
    filter_graph = (
        f"fps={spec.frame_rate},"
        "scale=360:360:force_original_aspect_ratio=increase,"
        "crop=360:360,setsar=1,split[s0][s1];"
        f"[s0]palettegen=max_colors={spec.colors}:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle"
    )
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", str(spec.start_seconds), "-t", str(spec.duration_seconds),
        "-i", str(source), "-an", "-filter_complex", filter_graph,
        "-loop", "0", "-y", str(temporary),
    ]
    try:
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
            raise MediaToolUnavailable("ffmpeg_not_found") from error
        except subprocess.TimeoutExpired as error:
            raise MediaProbeError("ffmpeg_timeout") from error
        if completed.returncode != 0 or not temporary.is_file():
            raise MediaProbeError("ffmpeg_failed")
        if temporary.stat().st_size > max_output_bytes:
            raise MediaProbeError("wallpaper_output_too_large")

        output_probe = probe_round_wallpaper(
            temporary,
            ffprobe=ffprobe,
            timeout_seconds=min(timeout_seconds, 30.0),
        )
        if (
            output_probe.container != "gif"
            or output_probe.width != 360
            or output_probe.height != 360
            or output_probe.has_audio
            or abs(output_probe.frame_rate - spec.frame_rate) > 0.5
            or not 2.9 <= output_probe.duration_seconds <= 5.1
        ):
            raise MediaProbeError("wallpaper_output_contract_failed")

        temporary.replace(destination)
        raw = destination.read_bytes()
        return {
            "schema_version": 1,
            "kind": "round_wallpaper_spike",
            "source_file_name": source.name,
            "target": {"board": "viewe-smartring-plus", "width": 360, "height": 360},
            "format": "gif",
            "duration_seconds": output_probe.duration_seconds,
            "frame_rate": output_probe.frame_rate,
            "colors": spec.colors,
            "has_audio": output_probe.has_audio,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "file_name": destination.name,
        }
    finally:
        temporary.unlink(missing_ok=True)
