"""实际ASR-adapter-3.10RPC-SDK-Runtime组合；仅固定源码与合成随机回环。"""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[3]


def extract(stage, ref, paths):
    data = subprocess.run(["git", "archive", "--format=tar", ref, *paths], cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for item in archive.getmembers():
            target = (stage / item.name).resolve()
            assert target.is_relative_to(stage.resolve())
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                assert item.isfile() and not item.linkname
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(item).read())


@pytest.fixture(scope="module")
def frozen_adapter_host(tmp_path_factory):
    ref = os.environ.get("LONGMEMORY_TEST_ADAPTER_HOST_REF")
    required = ["LONGMEMORY_TEST_HY_PYTHON", "LONGMEMORY_TEST_PY310", "LONGMEMORY_TEST_XIAOZHI_ROOT"]
    if not ref or not all(os.environ.get(name) for name in required):
        pytest.skip("explicit frozen AI ref/SDK/voice3.10/native repository required")
    assert len(ref) == 40 and all(char in "0123456789abcdef" for char in ref)
    stage = tmp_path_factory.mktemp("ae-frozen-adapter-sdk")
    extract(stage, ref, ["src/longmemory", "tests/fixtures", "tests/integration/test_hy_semantic_sdk.py",
        "tests/unit/methods/test_hy_candidate_response.py", "tests/unit/methods/test_hy_provider_transport.py"])
    extract(stage, "HEAD", ["scripts/development/xiaozhi"])
    for name in ("voice_proposal_adapter.py", "voice_asr_prefetch.py", "voice_proposal_rpc.py"):
        assert (stage / "scripts/development/xiaozhi" / name).read_bytes() == (ROOT / "scripts/development/xiaozhi" / name).read_bytes()
    return stage


@pytest.mark.parametrize("scenario", ["reset_worker", "metadata", "speaker", "date", "role", "history",
                                     "pcm_changed", "tools", "yield_cancel", "new_turn", "queued_cancel"])
def test_actual_native_asr_adapter_and_python310_formal_sdk_rpc(frozen_adapter_host, tmp_path, scenario):
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B",
        str(ROOT / "tests/fixtures/voice_proposal_adapter_sdk_host.py"), str(frozen_adapter_host), str(tmp_path), scenario],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=55,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr[-3000:]
    summary = json.loads(result.stdout)
    expected = ("suppressed_queued" if scenario == "queued_cancel" else "suppressed" if scenario == "yield_cancel"
                else "adopted" if scenario in {"reset_worker", "new_turn"} else "miss")
    assert summary["ok"] and summary["state"] == expected
    assert summary["prepare_count"] == (2 if scenario == "new_turn" else 1)
    assert summary["memory_items"] == 6 and summary["external_http_attempts"] == 0
    for secret in ("e" * 64, "检查资料", "合成回答", "原正式回答"):
        assert secret not in result.stdout + result.stderr
