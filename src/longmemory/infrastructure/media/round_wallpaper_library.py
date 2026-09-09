"""智能圆屏动态壁纸的本机素材库。

原视频可能很大，也可能伪装扩展名。素材库先在隔离目录接收文件，再用
ffprobe 校验实际媒体信息，最后用受限参数转码。只有源文件、预览文件和
清单都成功后，整个目录才会原子地进入可见素材库。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from .round_wallpaper import (
    MediaProbeError,
    MediaToolUnavailable,
    RoundWallpaperTranscodeSpec,
    probe_round_wallpaper,
    transcode_round_wallpaper_sample,
)


MAX_SOURCE_BYTES = 768 * 1024 * 1024
MAX_SOURCE_PIXELS = 7680 * 4320
MAX_SOURCE_FRAME_RATE = 120.0
MAX_SOURCE_DURATION_SECONDS = 3600.0
MAX_PREVIEW_BYTES = 4 * 1024 * 1024
_ITEM_ID = re.compile(r"wallpaper-[0-9a-f]{20}")
_STAGING_ID = re.compile(r"upload-[0-9a-f]{32}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_name(value: str | None) -> str:
    # multipart filename 是不可信输入：仅保留显示用文本，不用它构造路径。
    text = (value or "wallpaper-media").replace("\\", "/").rsplit("/", 1)[-1]
    text = "".join(character for character in text if character.isprintable()).strip()
    return (text or "wallpaper-media")[:160]


def resolve_media_tools(ffmpeg_dir: Path | None = None) -> tuple[str, str]:
    """解析已由用户安装的 FFmpeg，不在服务进程中下载依赖。"""

    configured = ffmpeg_dir
    if configured is None and os.environ.get("LONGMEMORY_FFMPEG_DIR"):
        configured = Path(os.environ["LONGMEMORY_FFMPEG_DIR"])
    if configured is not None:
        directory = configured.expanduser().resolve()
        ffmpeg = directory / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        ffprobe = directory / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if ffmpeg.is_file() and ffprobe.is_file():
            return str(ffmpeg), str(ffprobe)
        raise MediaToolUnavailable("ffmpeg_directory_invalid")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise MediaToolUnavailable("ffmpeg_not_found")
    return ffmpeg, ffprobe


class RoundWallpaperLibrary:
    """保存原视频与可预览转码，但不负责烧录或下发真机。"""

    def __init__(self, root: Path, *, ffmpeg_dir: Path | None = None):
        self.root = Path(root).resolve()
        self.staging_root = self.root / ".staging"
        self.ffmpeg_dir = ffmpeg_dir

    def describe(self) -> dict[str, object]:
        try:
            resolve_media_tools(self.ffmpeg_dir)
            tool_state = "ready"
        except MediaToolUnavailable:
            tool_state = "unavailable"
        return {
            "enabled": tool_state == "ready",
            "tool_state": tool_state,
            "max_upload_bytes": MAX_SOURCE_BYTES,
            "items": self.list_items(),
        }

    def create_staging(self) -> tuple[Path, Path]:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        directory = self.staging_root / f"upload-{uuid.uuid4().hex}"
        directory.mkdir()
        return directory, directory / "source.media"

    def discard_staging(self, directory: Path) -> None:
        directory = Path(directory).resolve()
        if directory.parent == self.staging_root and _STAGING_ID.fullmatch(directory.name):
            shutil.rmtree(directory, ignore_errors=True)

    def import_staging(
        self,
        directory: Path,
        *,
        original_filename: str | None,
        spec: RoundWallpaperTranscodeSpec,
    ) -> dict[str, object]:
        directory = Path(directory).resolve()
        source = directory / "source.media"
        if directory.parent != self.staging_root or not _STAGING_ID.fullmatch(directory.name):
            raise MediaProbeError("invalid_wallpaper_staging")
        if not source.is_file() or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
            raise MediaProbeError("invalid_wallpaper_source_size")
        spec.validate()
        ffmpeg, ffprobe = resolve_media_tools(self.ffmpeg_dir)
        probe = probe_round_wallpaper(source, ffprobe=ffprobe)
        if (
            probe.size_bytes > MAX_SOURCE_BYTES
            or probe.width * probe.height > MAX_SOURCE_PIXELS
            or probe.frame_rate > MAX_SOURCE_FRAME_RATE
            or probe.duration_seconds > MAX_SOURCE_DURATION_SECONDS
        ):
            raise MediaProbeError("wallpaper_source_outside_limits")
        if spec.start_seconds + spec.duration_seconds > probe.duration_seconds + 0.05:
            raise MediaProbeError("wallpaper_clip_outside_source")

        source_sha = _sha256(source)
        identity = json.dumps(
            {"source_sha256": source_sha, "spec": asdict(spec)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        item_id = f"wallpaper-{hashlib.sha256(identity).hexdigest()[:20]}"
        destination = self.root / item_id
        preview = directory / "preview.gif"
        output = transcode_round_wallpaper_sample(
            source,
            preview,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            spec=spec,
            max_output_bytes=MAX_PREVIEW_BYTES,
        )
        manifest: dict[str, object] = {
            "schema_version": 1,
            "id": item_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "ready",
            "source": {
                "display_name": _display_name(original_filename),
                "size_bytes": source.stat().st_size,
                "sha256": source_sha,
                "container": probe.container,
                "video_codec": probe.video_codec,
                "width": probe.width,
                "height": probe.height,
                "duration_seconds": probe.duration_seconds,
                "frame_rate": probe.frame_rate,
                "has_audio": probe.has_audio,
            },
            "clip": asdict(spec),
            "preview": {
                "file_name": "preview.gif",
                "size_bytes": output["size_bytes"],
                "sha256": output["sha256"],
                "width": 360,
                "height": 360,
                "format": "gif",
                "has_audio": False,
            },
            "delivery": {"device_published": False, "reason": "preview_only"},
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            self.discard_staging(directory)
            return self._load_item(destination)
        directory.replace(destination)
        return manifest

    def _load_item(self, directory: Path) -> dict[str, object]:
        if directory.parent != self.root or not _ITEM_ID.fullmatch(directory.name):
            raise MediaProbeError("invalid_wallpaper_id")
        payload = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("id") != directory.name or payload.get("state") != "ready":
            raise MediaProbeError("invalid_wallpaper_manifest")
        preview = payload.get("preview")
        if not isinstance(preview, dict) or preview.get("file_name") != "preview.gif":
            raise MediaProbeError("invalid_wallpaper_manifest")
        return payload

    def list_items(self) -> list[dict[str, object]]:
        if not self.root.is_dir():
            return []
        items: list[dict[str, object]] = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or not _ITEM_ID.fullmatch(directory.name):
                continue
            try:
                items.append(self._load_item(directory))
            except (OSError, ValueError, UnicodeError, MediaProbeError):
                continue
        return sorted(items, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def preview_path(self, item_id: str) -> Path:
        if not _ITEM_ID.fullmatch(item_id):
            raise MediaProbeError("invalid_wallpaper_id")
        directory = self.root / item_id
        manifest = self._load_item(directory)
        preview = directory / "preview.gif"
        expected = manifest["preview"]["sha256"]  # type: ignore[index]
        if not preview.is_file() or _sha256(preview) != expected:
            raise MediaProbeError("wallpaper_preview_integrity_failed")
        return preview

    def delivery_spec(self, item_id: str) -> dict[str, object]:
        """返回设备投递所需的最小字段，并再次复核预览文件。"""

        path = self.preview_path(item_id)
        manifest = self._load_item(self.root / item_id)
        preview = manifest["preview"]
        return {
            "item_id": item_id,
            "path": path,
            "sha256": preview["sha256"],
            "size_bytes": preview["size_bytes"],
        }
