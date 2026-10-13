"""下载发布边界只用合成资源，不能下载模型或读取个人配置。"""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile
import urllib.error

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/voice_restore/prepare_assets.py"
SPEC = importlib.util.spec_from_file_location("voice_restore_assets_test", SCRIPT)
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


def resource(content=b"synthetic model"):
    return {"name": "synthetic", "target": "models/sample.bin", "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "url": "https://example.invalid/model"}


class Response(io.BytesIO):
    def __init__(self, content, *, status=200, headers=None):
        super().__init__(content)
        self.status, self.headers = status, headers or {}


def test_publishes_only_complete_verified_download(tmp_path, monkeypatch):
    entry = resource()
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *a, **k: Response(b"synthetic model"))
    assets.download(entry, tmp_path)
    assert (tmp_path / entry["target"]).read_bytes() == b"synthetic model"
    assert not list(tmp_path.rglob("*.part"))


def test_lfs_weight_uses_payload_sha256_instead_of_pointer_blob(tmp_path):
    path = tmp_path / "weight.bin"
    path.write_bytes(b"synthetic model")
    entry = resource()
    entry["git_blob"] = hashlib.sha1(b"LFS pointer, not payload").hexdigest()
    assert assets.validate(path, entry) == entry["sha256"]


def test_modelscope_small_file_uses_explicit_range(tmp_path, monkeypatch):
    entry = resource()
    entry["range_required"] = True
    def response(request, **kwargs):
        assert request.headers["Range"] == "bytes=0-14"
        return Response(b"synthetic model", status=206,
                        headers={"Content-Range": "bytes 0-14/15"})
    monkeypatch.setattr(assets.urllib.request, "urlopen", response)
    assets.download(entry, tmp_path)
    assert (tmp_path / entry["target"]).read_bytes() == b"synthetic model"


@pytest.mark.parametrize("status", [403, 429])
def test_modelscope_rate_limit_stops_once_and_preserves_progress(tmp_path, monkeypatch, status):
    entry = resource()
    entry["url"] = "https://modelscope.cn/api/v1/models/example/repo"
    path = tmp_path / "models/sample.bin.part"
    path.parent.mkdir()
    path.write_bytes(b"synt")
    requests = []
    def limited(request, **kwargs):
        requests.append(request)
        body = io.BytesIO(json.dumps({"Code": 10013201001, "Message": "rate limited"}).encode())
        raise urllib.error.HTTPError(entry["url"], status, "Forbidden", {}, body)
    monkeypatch.setattr(assets.urllib.request, "urlopen", limited)
    with pytest.raises(assets.AssetDownloadError, match="ModelScope 当前限流"):
        assets.download(entry, tmp_path)
    assert len(requests) == 1
    assert path.read_bytes() == b"synt"
    assert not (tmp_path / "models/sample.bin").exists()


@pytest.mark.parametrize("body", [b'{}', b'[]', b'invalid json'])
def test_other_forbidden_response_is_not_claimed_to_be_a_rate_limit(tmp_path, monkeypatch, body):
    entry = resource()
    entry["url"] = "https://modelscope.cn/api/v1/models/example/repo"
    def forbidden(request, **kwargs):
        raise urllib.error.HTTPError(entry["url"], 403, "Forbidden", {}, io.BytesIO(body))
    monkeypatch.setattr(assets.urllib.request, "urlopen", forbidden)
    with pytest.raises(assets.AssetDownloadError, match="HTTP 403") as error:
        assets.download(entry, tmp_path)
    assert "当前限流" not in str(error.value)


@pytest.mark.parametrize("content", [b"truncated", b"corrupted model"])
def test_bad_download_keeps_partial_and_does_not_publish(tmp_path, monkeypatch, content):
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *a, **k: Response(content))
    with pytest.raises(ValueError):
        assets.download(resource(), tmp_path)
    assert not (tmp_path / "models/sample.bin").exists()
    assert (tmp_path / "models/sample.bin.part").exists()


def test_existing_invalid_resource_is_not_overwritten_or_redownloaded(tmp_path, monkeypatch):
    path = tmp_path / "models/sample.bin"
    path.parent.mkdir()
    path.write_bytes(b"owner file")
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *a, **k: pytest.fail("不得联网"))
    with pytest.raises(ValueError):
        assets.download(resource(), tmp_path)
    assert path.read_bytes() == b"owner file"


def test_partial_requires_exact_range_before_append(tmp_path, monkeypatch):
    partial = tmp_path / "models/sample.bin.part"
    partial.parent.mkdir()
    partial.write_bytes(b"synthetic ")
    def open_range(request, **kwargs):
        assert request.headers["Range"] == "bytes=10-14"
        return Response(b"model", status=206, headers={"Content-Range": "bytes 10-14/15"})
    monkeypatch.setattr(assets.urllib.request, "urlopen", open_range)
    assets.download(resource(), tmp_path)
    assert (tmp_path / "models/sample.bin").read_bytes() == b"synthetic model"


def test_ignored_range_does_not_damage_partial(tmp_path, monkeypatch):
    partial = tmp_path / "models/sample.bin.part"
    partial.parent.mkdir()
    partial.write_bytes(b"synthetic ")
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *a, **k: Response(b"synthetic model"))
    with pytest.raises(ValueError, match="断点续传"):
        assets.download(resource(), tmp_path)
    assert partial.read_bytes() == b"synthetic "


def test_empty_partial_can_continue(tmp_path, monkeypatch):
    path = tmp_path / "models/sample.bin.part"
    path.parent.mkdir()
    path.touch()
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *a, **k: Response(b"synthetic model"))
    assets.download(resource(), tmp_path)
    assert (tmp_path / "models/sample.bin").is_file()


def test_large_resource_uses_bounded_ranges_and_full_file_digest(tmp_path, monkeypatch):
    content = b"synthetic model"
    requested = []
    monkeypatch.setattr(assets, "SEGMENT_BYTES", 4)
    def response(request, **kwargs):
        start, end = map(int, request.headers["Range"][6:].split("-"))
        requested.append((start, end))
        return Response(content[start:end + 1], status=206, headers={
            "Content-Range": f"bytes {start}-{end}/{len(content)}",
            "Content-Length": str(end - start + 1),
        })
    monkeypatch.setattr(assets.urllib.request, "urlopen", response)
    assert assets.download(resource(), tmp_path) == hashlib.sha256(content).hexdigest()
    assert requested == [(0, 3), (4, 7), (8, 11), (12, 14)]
    assert (tmp_path / "models/sample.bin").read_bytes() == content


def test_server_can_cap_a_range_further_without_repeating_bytes(tmp_path, monkeypatch):
    content = b"synthetic model"
    monkeypatch.setattr(assets, "SEGMENT_BYTES", 8)
    def response(request, **kwargs):
        start, requested_end = map(int, request.headers["Range"][6:].split("-"))
        end = min(start + 2, requested_end)
        return Response(content[start:end + 1], status=206,
                        headers={"Content-Range": f"bytes {start}-{end}/{len(content)}"})
    monkeypatch.setattr(assets.urllib.request, "urlopen", response)
    assets.download(resource(), tmp_path)
    assert (tmp_path / "models/sample.bin").read_bytes() == content


def test_truncated_range_keeps_prefix_and_explicit_rerun_resumes(tmp_path, monkeypatch):
    content = b"synthetic model"
    monkeypatch.setattr(assets, "SEGMENT_BYTES", 4)
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *a, **k: Response(
        content[:3], status=206, headers={"Content-Range": "bytes 0-3/15", "Content-Length": "4"}))
    with pytest.raises(ValueError, match="已保留 3/15"):
        assets.download(resource(), tmp_path)
    assert (tmp_path / "models/sample.bin.part").read_bytes() == content[:3]
    requested = []
    def response(request, **kwargs):
        start, end = map(int, request.headers["Range"][6:].split("-"))
        requested.append(start)
        return Response(content[start:end + 1], status=206,
                        headers={"Content-Range": f"bytes {start}-{end}/15"})
    monkeypatch.setattr(assets.urllib.request, "urlopen", response)
    assets.download(resource(), tmp_path)
    assert requested[0] == 3
    assert (tmp_path / "models/sample.bin").read_bytes() == content


@pytest.mark.parametrize("content_range", ["bytes 0-3/15", "bytes 4-7/16", "bytes 4-8/15"])
def test_wrong_range_does_not_append_to_prefix(tmp_path, monkeypatch, content_range):
    partial = tmp_path / "models/sample.bin.part"
    partial.parent.mkdir()
    partial.write_bytes(b"synt")
    monkeypatch.setattr(assets, "SEGMENT_BYTES", 4)
    monkeypatch.setattr(assets.urllib.request, "urlopen", lambda *a, **k: Response(
        b"heti", status=206, headers={"Content-Range": content_range}))
    with pytest.raises(ValueError, match="断点续传"):
        assets.download(resource(), tmp_path)
    assert partial.read_bytes() == b"synt"


def test_completed_segments_still_require_the_expected_digest(tmp_path, monkeypatch):
    content = b"corrupted model"
    monkeypatch.setattr(assets, "SEGMENT_BYTES", 4)
    def response(request, **kwargs):
        start, end = map(int, request.headers["Range"][6:].split("-"))
        return Response(content[start:end + 1], status=206,
                        headers={"Content-Range": f"bytes {start}-{end}/15"})
    monkeypatch.setattr(assets.urllib.request, "urlopen", response)
    with pytest.raises(ValueError, match="SHA-256"):
        assets.download(resource(), tmp_path)
    assert not (tmp_path / "models/sample.bin").exists()
    assert (tmp_path / "models/sample.bin.part").read_bytes() == content


def test_manifest_cannot_escape_resource_root(tmp_path):
    with pytest.raises(ValueError, match="超出"):
        assets.local_path("../owner.bin", tmp_path)


def test_tool_archive_cannot_escape_resource_root(tmp_path):
    archive = tmp_path / "downloads/ffmpeg-9.0.1-essentials_build.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("ffmpeg-9.0.1-essentials_build/../../../owner.bin", b"bad")
    with pytest.raises(ValueError, match="路径不合法"):
        assets.unpack_tools(tmp_path)
    assert not (tmp_path.parent / "owner.bin").exists()


def test_verified_tools_can_unpack_without_running_them(tmp_path, monkeypatch):
    import tarfile
    package_path = tmp_path / "downloads"
    package_path.mkdir()
    with zipfile.ZipFile(package_path / "ffmpeg-9.0.1-essentials_build.zip", "w") as package:
        package.writestr("ffmpeg-9.0.1-essentials_build/bin/ffmpeg.exe", b"synthetic exe")
    content = b"synthetic opus"
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as package:
        member = tarfile.TarInfo("Library/bin/opus.dll")
        member.size = len(content)
        package.addfile(member, io.BytesIO(content))
    with zipfile.ZipFile(package_path / "libopus-1.6.1-h6a83c73_0.conda", "w") as package:
        package.writestr("pkg-libopus-1.6.1-h6a83c73_0.tar.zst", b"synthetic zstd")
    monkeypatch.setattr(assets, "OPUS_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(assets.shutil, "which", lambda name: "synthetic-7z")
    monkeypatch.setattr(assets.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=tar_stream.getvalue()))
    assets.unpack_tools(tmp_path)
    assets.unpack_tools(tmp_path)
    assert (tmp_path / "tools/ffmpeg/bin/ffmpeg.exe").read_bytes() == b"synthetic exe"
