"""AE完整有效输入跨解释器检查；冻结业务源码，只有合成SDK/回环供应商。"""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def frozen_sdk_input_host(tmp_path_factory):
    ref = os.environ.get("LONGMEMORY_TEST_SDK_HOST_REF")
    sdk, voice = os.environ.get("LONGMEMORY_TEST_HY_PYTHON"), os.environ.get("LONGMEMORY_TEST_PY310")
    if not ref or not sdk or not voice:
        pytest.skip("explicit fixed AI ref, owner-installed SDK and Python3.10 required")
    assert len(ref) == 40 and all(char in "0123456789abcdef" for char in ref)
    assert Path(sdk).is_file() and Path(voice).is_file()
    paths = ["src/longmemory", "tests/fixtures", "tests/integration/test_hy_semantic_sdk.py",
             "tests/unit/methods/test_hy_candidate_response.py", "tests/unit/methods/test_hy_provider_transport.py"]
    data = subprocess.run(["git", "archive", "--format=tar", ref, *paths], cwd=ROOT, check=True, capture_output=True).stdout
    stage = tmp_path_factory.mktemp("ae-frozen-sdk-host")
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
    scripts = stage / "scripts/development/xiaozhi"
    scripts.mkdir(parents=True)
    for name in ("voice_preemptive.py", "voice_preemptive_stream.py", "voice_preemptive_input.py", "voice_proposal_rpc.py"):
        content = subprocess.run(["git", "show", "HEAD:scripts/development/xiaozhi/" + name], cwd=ROOT,
            check=True, capture_output=True).stdout
        assert content == (ROOT / "scripts/development/xiaozhi" / name).read_bytes()
        (scripts / name).write_bytes(content)
    return stage


@pytest.mark.parametrize("change", ["none", "metadata", "speaker", "current", "history", "date", "tools"])
def test_real_sdk_formal_routes_and_python310_preserve_effective_input(frozen_sdk_input_host, tmp_path, change):
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B",
        str(ROOT / "tests/fixtures/voice_proposal_rpc_sdk_input_host.py"), str(frozen_sdk_input_host), str(tmp_path), change],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr[-2200:]
    output = json.loads(result.stdout)
    assert output == {"ok": True, "state": "adopted" if change == "none" else "miss", "prepare_count": 1,
                      "attempt_count": int(change != "tools"), "memory_items": 6, "sdk": "2.0.3", "external_http_attempts": 0}
    for secret in ("e" * 64, "合成声纹", "原样保留", "合成回答"):
        assert secret not in result.stdout + result.stderr
