import json
from pathlib import Path
import subprocess

import pytest

from longmemory.infrastructure.media.round_wallpaper import (
    MediaProbeError,
    MediaToolUnavailable,
    RoundWallpaperTranscodeSpec,
    probe_round_wallpaper,
    transcode_round_wallpaper_sample,
)


def test_probe_round_wallpaper_returns_stable_media_facts(tmp_path, monkeypatch):
    source = tmp_path / "角色壁纸.mp4"
    source.write_bytes(b"synthetic-not-real-media")
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "60000/1001",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"format_name": "mov,mp4", "duration": "12.3456", "size": "727445107"},
    }

    def fake_run(command, **kwargs):
        assert command[-1] == str(source.resolve())
        assert kwargs["timeout"] == 30.0
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = probe_round_wallpaper(source)

    assert result.to_dict() == {
        "file_name": "角色壁纸.mp4",
        "size_bytes": 727445107,
        "container": "mov,mp4",
        "duration_seconds": 12.346,
        "video_codec": "h264",
        "width": 1920,
        "height": 1080,
        "frame_rate": 59.94,
        "has_audio": True,
    }


def test_probe_round_wallpaper_reports_missing_tool(tmp_path, monkeypatch):
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"synthetic")

    def missing(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(MediaToolUnavailable, match="ffprobe_not_found"):
        probe_round_wallpaper(source)


def test_probe_round_wallpaper_treats_windows_execution_denial_as_unavailable(tmp_path, monkeypatch):
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"synthetic")

    def denied(*_args, **_kwargs):
        raise PermissionError

    monkeypatch.setattr(subprocess, "run", denied)
    with pytest.raises(MediaToolUnavailable, match="ffprobe_not_found"):
        probe_round_wallpaper(source)


def test_probe_round_wallpaper_rejects_ambiguous_video_streams(tmp_path, monkeypatch):
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"synthetic")

    def fake_run(command, **_kwargs):
        payload = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 360, "height": 360,
                 "avg_frame_rate": "10/1"},
                {"codec_type": "video", "codec_name": "h264", "width": 360, "height": 360,
                 "avg_frame_rate": "10/1"},
            ],
            "format": {"format_name": "mov,mp4", "duration": "5", "size": "1024"},
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(MediaProbeError, match="expected_one_video_stream"):
        probe_round_wallpaper(source)


def test_probe_round_wallpaper_does_not_expose_tool_stderr(tmp_path, monkeypatch):
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"synthetic")

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, "", "sensitive local path")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(MediaProbeError, match="^ffprobe_failed$"):
        probe_round_wallpaper(source)


def test_transcode_round_wallpaper_sample_is_atomic_and_returns_manifest(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic-source")
    destination = tmp_path / "derived/sample.gif"

    def fake_run(command, **_kwargs):
        if command[0] == "fake-ffmpeg":
            assert "-an" in command
            assert "fps=10" in command[command.index("-filter_complex") + 1]
            Path(command[-1]).write_bytes(b"GIF89a-synthetic")
            return subprocess.CompletedProcess(command, 0, "", "")
        payload = {
            "streams": [{"codec_type": "video", "codec_name": "gif", "width": 360, "height": 360,
                         "avg_frame_rate": "10/1"}],
            "format": {"format_name": "gif", "duration": "5", "size": "16"},
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = transcode_round_wallpaper_sample(
        source,
        destination,
        ffmpeg="fake-ffmpeg",
        ffprobe="fake-ffprobe",
    )

    assert destination.read_bytes() == b"GIF89a-synthetic"
    assert result["file_name"] == "sample.gif"
    assert result["size_bytes"] == 16
    assert result["frame_rate"] == 10.0
    assert result["has_audio"] is False
    assert len(result["sha256"]) == 64
    assert not list(destination.parent.glob("*.tmp.gif"))


@pytest.mark.parametrize(
    ("spec", "code"),
    [
        (RoundWallpaperTranscodeSpec(duration_seconds=8), "invalid_wallpaper_duration"),
        (RoundWallpaperTranscodeSpec(frame_rate=30), "invalid_wallpaper_frame_rate"),
        (RoundWallpaperTranscodeSpec(colors=256), "invalid_wallpaper_colors"),
    ],
)
def test_transcode_round_wallpaper_rejects_unbounded_parameters(tmp_path, spec, code):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic")
    with pytest.raises(MediaProbeError, match=code):
        transcode_round_wallpaper_sample(source, tmp_path / "sample.gif", spec=spec)
