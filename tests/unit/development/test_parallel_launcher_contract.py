"""真实 HTTP 主机与浏览器替身控制器组合；不使用前端依赖或日用配置。"""

import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading


def test_browser_preview_implements_observed_controller_contract(tmp_path, monkeypatch):
    # G 新的 events/请求 ID 边界必须被 F 的实际浏览器替身实现；不能只改单位测试假对象。
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    script = Path(__file__).resolve().parents[3] / 'scripts/development/playwright_launcher.py'
    spec = importlib.util.spec_from_file_location('parallel_launcher_preview', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    controller = module.PreviewController(tmp_path)
    dist = tmp_path / 'dist'
    (dist / '.vite').mkdir(parents=True)
    (dist / '.vite/manifest.json').write_text('{}', encoding='utf-8')
    token = 'synthetic-integration-token'
    server = module.create_server(controller, dist, token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
    try:
        client.request('GET', '/api/launcher/observability')
        response = client.getresponse()
        assert response.status == 401
        response.read()
        client.request('POST', '/api/launcher/actions', body=json.dumps({'action': 'start'}),
            headers={'Authorization': 'Bearer ' + token, 'Origin': server.origin,
                     'Content-Type': 'application/json'})
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read())['state'] == 'starting'
        request_id = response.headers['X-Request-Id']
        client.request('GET', '/api/launcher/observability', headers={'Authorization': 'Bearer ' + token})
        response = client.getresponse()
        assert response.status == 200
        summary = json.loads(response.read())
        assert summary['device_playback'] == 'unconfirmed'
        assert any(row['request_id'] == request_id and row['action'] == 'start' for row in summary['events'])
        assert token not in json.dumps(summary)
        assert controller.settings['voice'] is False
    finally:
        client.close()
        server.shutdown(); server.server_close(); thread.join(timeout=3)
        controller.events.close()
