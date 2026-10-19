"""真实子进程的协议/生命周期；不导入 SDK、不访问网络。"""

import json
from pathlib import Path
import sys

import pytest

from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
from longmemory.methods.hy_memory.settings import HySettings


SETTINGS = HySettings(user_id="w-synthetic-process")


def client_for(tmp_path, response_code):
    # 启动回执合法，第二个请求才触发故障，验证已启动 worker 的清理。
    script = (
        "import json,sys,time\n"
        "first=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'id':first['id'],'ok':True,'result':{'ready':True}}),flush=True)\n"
        "request=json.loads(sys.stdin.readline())\n" + response_code
    )
    return HyProcessClient(python=Path(sys.executable), workspace=tmp_path,
        settings=SETTINGS, create=True,
        command=[sys.executable, "-I", "-X", "utf8", "-B", "-c", script])


@pytest.mark.parametrize("response", [
    {"id": 2, "ok": True},  # 成功包必须有 result。
    {"id": True, "ok": True, "result": {}},
    {"id": 2.0, "ok": True, "result": {}},
    {"id": 99, "ok": True, "result": {}},
    {"id": 2, "ok": "yes", "result": {}},
])
def test_malformed_response_stops_worker(tmp_path, response):
    client = client_for(tmp_path, "print(" + repr(json.dumps(response)) + ",flush=True)\ntime.sleep(30)\n")
    client.timeout = 0.1
    try:
        with pytest.raises(HyResponseError, match="transport_failed_state_unknown"):
            client.diagnostics()
        assert client._closed and client._process.poll() is not None
    finally:
        client.close()


@pytest.mark.parametrize("code", ["sys.exit(7)\n", "time.sleep(30)\n"])
def test_crash_and_timeout_stop_worker(tmp_path, code):
    client = client_for(tmp_path, code)
    client.timeout = 0.1
    try:
        with pytest.raises(HyResponseError, match="transport_failed_state_unknown"):
            client.diagnostics()
        assert client._process.poll() is not None
    finally:
        client.close()


def test_operation_error_does_not_disclose_worker_error_text(tmp_path):
    response = {"id": 2, "ok": False, "error_type": "RuntimeError",
                "error": "synthetic-private-body-and-key"}
    client = client_for(tmp_path, "print(" + repr(json.dumps(response)) + ",flush=True)\n"
        "request=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'id':request['id'],'ok':True,'result':{'closed':True}}),flush=True)\n")
    try:
        with pytest.raises(HyResponseError, match="operation_failed_RuntimeError_state_unknown") as failure:
            client.diagnostics()
        assert "private" not in str(failure.value)
    finally:
        client.close()


def test_startup_malformed_response_also_reaps_worker(tmp_path, monkeypatch):
    from longmemory.methods.hy_memory import process_client
    original = process_client.subprocess.Popen
    children = []
    def record_child(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(process_client.subprocess, "Popen", record_child)
    script = "import sys,time; sys.stdin.readline(); print('{\"id\":true,\"ok\":true,\"result\":{}}',flush=True); time.sleep(30)"
    with pytest.raises(HyResponseError, match="transport_failed_state_unknown"):
        HyProcessClient(python=Path(sys.executable), workspace=tmp_path,
            settings=SETTINGS, create=True, command=[sys.executable, "-I", "-c", script])
    assert len(children) == 1 and children[0].poll() is not None
