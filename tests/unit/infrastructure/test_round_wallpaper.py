import json
from pathlib import Path
import subprocess

import pytest

from longmemory.infrastructure.media.round_wallpaper import (
    MediaProbeError,
    MediaToolUnavailable,
    probe_round_wallpaper,
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
