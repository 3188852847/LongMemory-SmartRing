from pathlib import Path
import subprocess

import pytest

from longmemory.infrastructure.media.round_wallpaper import (
    RoundWallpaperProbe,
    RoundWallpaperTranscodeSpec,
)
from longmemory.infrastructure.media.round_wallpaper_library import RoundWallpaperLibrary


def test_library_commits_only_validated_source_and_preview(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "ffmpeg.exe").touch()
    (tools / "ffprobe.exe").touch()
    library = RoundWallpaperLibrary(tmp_path / "library", ffmpeg_dir=tools)
    staging, source = library.create_staging()
    source.write_bytes(b"synthetic-video")

    def probe(path, **_kwargs):
        return RoundWallpaperProbe(path.name, path.stat().st_size, "mov,mp4", 120.0,
                                   "h264", 3840, 2160, 60.0, True)

    def transcode(_source, destination, **_kwargs):
        destination.write_bytes(b"GIF89a-preview")
        return {"size_bytes": 14, "sha256": "b" * 64}

    monkeypatch.setattr(
        "longmemory.infrastructure.media.round_wallpaper_library.probe_round_wallpaper", probe
    )
    monkeypatch.setattr(
        "longmemory.infrastructure.media.round_wallpaper_library.transcode_round_wallpaper_sample",
        transcode,
    )
    item = library.import_staging(
        staging,
        original_filename="C:\\private\\爱莉希雅.mp4",
        spec=RoundWallpaperTranscodeSpec(start_seconds=60),
    )

    assert item["source"]["display_name"] == "爱莉希雅.mp4"
    assert item["source"]["has_audio"] is True
    assert item["delivery"] == {"device_published": False, "reason": "preview_only"}
    assert not staging.exists()
    assert len(library.list_items()) == 1
    # 真实哈希不会信任转码器传回的错误值，因此预览校验应失败。
    try:
        library.preview_path(item["id"])
    except Exception as error:
        assert str(error) == "wallpaper_preview_integrity_failed"
    else:
        raise AssertionError("预览哈希不一致应被拒绝")


def test_library_discards_only_its_own_staging_directory(tmp_path):
    library = RoundWallpaperLibrary(tmp_path / "library")
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "important.txt").write_text("keep", encoding="utf-8")

    library.discard_staging(outside)

    assert (outside / "important.txt").read_text(encoding="utf-8") == "keep"


def test_library_real_ffmpeg_roundtrip_when_local_tools_exist(tmp_path):
    tools = Path(__file__).resolve().parents[3] / 'local/tools/ffmpeg/bin'
    if not (tools / "ffmpeg.exe").is_file() or not (tools / "ffprobe.exe").is_file():
        pytest.skip("本机未安装用户提供的 FFmpeg")
    source = tmp_path / "synthetic.mp4"
    completed = subprocess.run(
        [str(tools / "ffmpeg.exe"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=640x360:rate=10:duration=4", "-an", "-y", str(source)],
        check=False, capture_output=True, timeout=30,
    )
    assert completed.returncode == 0
    library = RoundWallpaperLibrary(tmp_path / "library", ffmpeg_dir=tools)
    staging, uploaded = library.create_staging()
    source.replace(uploaded)

    item = library.import_staging(
        staging, original_filename="synthetic.mp4",
        spec=RoundWallpaperTranscodeSpec(start_seconds=0, duration_seconds=3, frame_rate=8, colors=64),
    )

    assert item["preview"]["width"] == 360
    assert item["preview"]["has_audio"] is False
    assert library.preview_path(item["id"]).read_bytes().startswith(b"GIF")
