"""使用合成受管进程和临时配置验收 HTTP 启动器，绝不连接个人服务。"""

import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / 'scripts/development/launcher'
sys.path.insert(0, str(DIRECTORY))
try:
    import controller
    import web_app
    from control import LauncherControl, request_control
    from preferences import save_model_profile, save_preferences, save_tts_backend
finally:
    sys.path.pop(0)


def test_launcher_window_uses_existing_browser_with_argument_list(tmp_path):
    browser = tmp_path / 'Microsoft/Edge/Application/msedge.exe'
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b'synthetic-browser')
    url = 'http://127.0.0.1:12345/#token=synthetic'
    assert web_app.launcher_window_command(url, environment={'ProgramFiles': str(tmp_path)}) == [
        str(browser), '--app=' + url, '--window-size=1040,800']
    assert web_app.launcher_window_command(url, environment={}) is None
    with pytest.raises(ValueError):
        web_app.launcher_window_command('https://outside.example/', environment={})


def test_launcher_window_falls_back_without_changing_browser(monkeypatch):
    monkeypatch.setattr(web_app, 'launcher_window_command', lambda _: None)
    calls = []
    monkeypatch.setattr(web_app.webbrowser, 'open', lambda url, **kwargs: calls.append((url, kwargs)) or True)
    assert web_app.open_launcher_window('http://127.0.0.1:12345/')
    assert calls == [('http://127.0.0.1:12345/', {'new': 1})]


class FakeManager:
    def __init__(self):
        self.services = {}
        self.options = None
        self.health = False
        self.stop_count = 0
        self.failure = None
        self.exit_code = None
        self.stop_failure = False

    def start(self, options):
        self.options = options
        if self.failure:
            raise self.failure
        self.services['console'] = SimpleNamespace(process=SimpleNamespace(poll=lambda: self.exit_code))

    def stop(self):
        self.stop_count += 1
        if self.stop_failure:
            raise RuntimeError('synthetic stop failure')
        self.services.clear()

    def ready(self):
        return self.health

    def local_tts_ready(self):
        return False

    def publish_status(self, *args, **kwargs):
        pass


@pytest.fixture
def panel(tmp_path):
    manager = FakeManager()
    opened = []
    panel = controller.LauncherController(tmp_path, manager=manager, opener=opened.append)
    panel.opened_urls = opened
    yield panel
    panel.events.close()


@pytest.fixture
def host(panel, tmp_path):
    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'launcher.html').write_text('<html><meta name="style-nonce" content="__LONGMEMORY_NONCE__"/>synthetic</html>', encoding='utf-8')
    (dist / 'assets/app.js').write_text('console.log("synthetic")', encoding='utf-8')
    (dist / '.vite').mkdir()
    (dist / '.vite/manifest.json').write_text(json.dumps({'launcher.html': {'file': 'assets/app.js'}}), encoding='utf-8')
    server = web_app.create_server(panel, dist, token='synthetic-token-which-is-long-enough')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join()
    server.server_close()


def request(host, method, path, body=None, *, token=True, headers=None):
    client = http.client.HTTPConnection('127.0.0.1', host.server_port, timeout=5)
    fields = {'Authorization': 'Bearer ' + host.token} if token else {}
    if body is not None:
        fields['Content-Type'] = 'application/json'
        body = json.dumps(body)
    fields.update(headers or {})
    try:
        client.request(method, path, body=body, headers=fields)
        response = client.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data
    finally:
        client.close()


def test_rebuilt_assets_use_new_manifest_without_host_restart(host):
    (host.dist / 'assets/new-build.js').write_text('console.log("new synthetic build")', encoding='utf-8')
    (host.dist / '.vite/manifest.json').write_text(
        json.dumps({'launcher.html': {'file': 'assets/new-build.js'}}), encoding='utf-8')
    assert request(host, 'GET', '/react-chat/assets/new-build.js', token=False)[0] == 200
    assert request(host, 'GET', '/react-chat/assets/app.js', token=False)[0] == 404
    (host.dist / '.vite/manifest.json').write_text('{incomplete', encoding='utf-8')
    assert request(host, 'GET', '/', token=False)[0] == 503


def test_status_trace_matches_response_header_and_excludes_token(host):
    code, headers, _ = request(host, 'GET', '/api/launcher/status')
    assert code == 200
    path = host.controller.root / 'data/logs/launcher-events.jsonl'
    row = json.loads(path.read_text(encoding='utf-8').splitlines()[-1])
    assert row['request_id'] == headers['X-Request-Id']
    assert row['event'] == 'phase_changed'
    assert host.token not in path.read_text(encoding='utf-8')


def test_start_readiness_stop_and_console(panel):
    assert panel.snapshot()['state'] == 'stopped'
    assert panel.action('start')['state'] == 'starting'
    panel.perform_pending()
    panel.tick()
    assert panel.snapshot()['console_url'] is None
    panel.manager.health = True
    panel.tick()
    assert panel.snapshot()['state'] == 'ready'
    panel.action('open_console')
    assert panel.opened_urls == ['http://127.0.0.1:8767/chat-react']
    assert panel.manager.options.allow_memory_delete is True
    panel.action('stop')
    panel.perform_pending()
    assert panel.snapshot()['state'] == 'stopped'
    assert panel.manager.stop_count == 1


def test_start_failure_timeout_and_child_exit(panel):
    panel.manager.failure = ValueError('合成配置不完整，未启动服务。')
    panel.action('start')
    panel.perform_pending()
    assert panel.snapshot()['state'] == 'failed'
    panel.manager.failure = None
    panel.action('start')
    panel.perform_pending()
    panel.started -= 91
    panel.tick()
    assert panel.snapshot()['state'] == 'failed'
    assert not panel.manager.services
    panel.action('start')
    panel.perform_pending()
    panel.manager.exit_code = 3
    panel.tick()
    assert panel.snapshot()['state'] == 'failed'
    assert '退出码 3' in panel.snapshot()['message']


def test_shutdown_stops_before_closing_and_failure_keeps_host(panel):
    panel.action('start')
    panel.perform_pending()
    panel.manager.health = True
    panel.tick()
    panel.manager.stop_failure = True
    panel.action('shutdown')
    panel.perform_pending()
    assert not panel.shutdown_requested.is_set()
    assert panel.snapshot()['state'] == 'failed'
    assert panel.snapshot()['can_start'] is False
    panel.manager.stop_failure = False
    panel.action('shutdown')
    panel.perform_pending()
    assert panel.shutdown_requested.is_set()
    assert not panel.manager.services


def test_stop_can_be_queued_while_starting(panel):
    panel.action('start')
    panel.action('stop')
    panel.perform_pending()
    panel.tick()
    assert panel.snapshot()['state'] == 'stopping'
    panel.perform_pending()
    assert panel.snapshot()['state'] == 'stopped'


def test_settings_preserve_paths_choices_and_versioned_consent(panel):
    settings = panel.snapshot()
    panel.update_settings({'voice': True, 'model_profile': 'official',
                           'voice_model_profile': 'official', 'http_risk_ack': True,
                           'allow_memory_delete': False}, settings['settings_revision'])
    saved = json.loads(panel.paths['launcher'].read_text(encoding='utf-8'))
    assert saved['http_risk_ack_version'] == 'campus-http-v1'
    assert 'allow_memory_delete' not in saved
    assert panel.snapshot()['settings']['allow_memory_delete'] is False
    assert controller.LauncherController(panel.root, manager=FakeManager()).snapshot()['settings']['allow_memory_delete'] is True
    assert panel._options().model_profile == 'official'
    with pytest.raises(controller.ControllerError, match='刷新'):
        panel.update_settings({'voice': False}, settings['settings_revision'])
    for data in ({'database': 'arbitrary.db'}, {'voice': 'false'}, {'shell': 'cmd'}, {'lan_ip': '8.8.8.8'}):
        with pytest.raises(controller.ControllerError):
            panel.update_settings(data, panel.revision())


def test_pointer_change_conflicts_and_start_absorbs_latest(panel):
    revision = panel.revision()
    save_model_profile(panel.paths['model'], 'official')
    save_tts_backend(panel.paths['tts'], 'cosyvoice3')
    with pytest.raises(controller.ControllerError):
        panel.update_settings({'model_profile': 'campus'}, revision)
    panel.action('start')
    panel.perform_pending()
    assert panel.manager.options.model_profile == 'official'
    with pytest.raises(controller.ControllerError):
        panel.update_settings({'voice': True}, panel.revision())


def test_auth_origin_host_and_safe_errors(host):
    status, _, data = request(host, 'GET', '/api/launcher/status', token=False)
    assert status == 401 and json.loads(data)['error'] == 'unauthorized'
    for headers in ({'Origin': 'https://evil.example'}, {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
        assert request(host, 'GET', '/api/launcher/status', headers=headers)[0] == 403
        assert request(host, 'POST', '/api/launcher/actions', {'action': 'start'}, headers=headers)[0] == 403
    assert request(host, 'POST', '/api/launcher/actions', {'action': 'start'}, token=False)[0] == 401
    status, fields, data = request(host, 'GET', '/api/launcher/status', headers={'Origin': host.origin})
    assert status == 200 and json.loads(data)['state'] == 'stopped'
    assert 'Access-Control-Allow-Origin' not in fields
    assert host.token.encode() not in data
    assert request(host, 'POST', '/api/launcher/actions', {'action': 'execute', 'command': 'cmd.exe'})[0] == 400


def test_static_only_dist_assets_and_traversal(host, tmp_path):
    assert request(host, 'GET', '/')[0] == 200
    assert request(host, 'GET', '/react-chat/assets/app.js')[0] == 200
    (host.dist / 'secret.py').write_text('secret', encoding='utf-8')
    (host.dist / 'assets/private.js').write_text('private', encoding='utf-8')
    for path in ('/secret.py', '/api/launcher/status?token=bad', '/react-chat/assets/../secret.py',
                 '/react-chat/assets/%2e%2e/secret.py', '/react-chat/assets/..%5csecret.py',
                 '/react-chat/assets/%252e%252e/secret.py', '/react-chat/assets/C:/secret.js',
                 '/react-chat/assets/private.js', '/.vite/manifest.json'):
        assert request(host, 'GET', path)[0] in {400, 404}
    assert request(host, 'GET', '/scripts/development/launcher/controller.py')[0] == 404


def test_html_nonce_matches_csp_and_changes_per_response(host):
    _, fields, data = request(host, 'GET', '/')
    assert b'__LONGMEMORY_NONCE__' not in data
    nonce = data.decode().split('content="')[1].split('"')[0]
    assert f"'nonce-{nonce}'" in fields['Content-Security-Policy']
    assert "'unsafe-inline'" not in fields['Content-Security-Policy']
    assert request(host, 'GET', '/')[2] != data


def test_assets_directory_junction_cannot_escape_dist(host, tmp_path):
    (host.dist / 'assets').rename(host.dist / 'original-assets')
    outside = tmp_path / 'private-assets'
    outside.mkdir()
    (outside / 'app.js').write_text('outside private bytes', encoding='utf-8')
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J',
                                 str(host.dist / 'assets'), str(outside)], capture_output=True)
        assert result.returncode == 0
    else:
        (host.dist / 'assets').symlink_to(outside, target_is_directory=True)
    assert request(host, 'GET', '/react-chat/assets/app.js')[0] == 404


def test_snapshot_retries_external_pointer_change(panel, monkeypatch):
    original = panel.settings
    changed = False
    def changed_once():
        nonlocal changed
        values = original()
        if not changed:
            save_model_profile(panel.paths['model'], 'official')
            changed = True
        return values
    monkeypatch.setattr(panel, 'settings', changed_once)
    snapshot = panel.snapshot()
    assert snapshot['settings']['model_profile'] == 'official'
    assert snapshot['settings_revision'] == panel.revision()


def test_settings_write_failure_rolls_back_only_owned_bytes(panel, monkeypatch):
    save_preferences(panel.paths['launcher'], panel.settings())
    before = panel.paths['launcher'].read_bytes()
    def failed_write(*args):
        # 模拟另一个页面在失败前已保存新 model 指针；回退不覆盖它。
        save_model_profile(panel.paths['model'], 'official')
        raise OSError('synthetic failure')
    monkeypatch.setattr(controller, 'save_memory_backend', failed_write)
    with pytest.raises(controller.ControllerError, match='完整保存'):
        panel.update_settings({'voice': True}, panel.revision())
    assert panel.paths['launcher'].read_bytes() == before
    assert panel.settings()['model_profile'] == 'official'


def test_stop_request_during_slow_ready_check_keeps_stopping(panel):
    panel.action('start')
    panel.perform_pending()
    def ready_with_stop():
        panel.action('stop')
        return True
    panel.manager.ready = ready_with_stop
    panel.tick()
    assert panel.snapshot()['state'] == 'stopping'
    panel.perform_pending()
    assert panel.snapshot()['state'] == 'stopped'


def test_shutdown_status_is_observed_only_after_stop(host):
    host.controller.action('start')
    host.controller.perform_pending()
    host.controller.action('shutdown')
    assert not host.controller.shutdown_requested.is_set()
    host.controller.perform_pending()
    status = json.loads(request(host, 'GET', '/api/launcher/status')[2])
    assert status['state'] == 'stopped' and status['shutdown_complete'] is True
    assert host.shutdown_observed.is_set()
    assert status['can_start'] is False


def test_settings_http_conflict_and_actions(host):
    snapshot = json.loads(request(host, 'GET', '/api/launcher/status')[2])
    revision = snapshot['settings_revision']
    assert request(host, 'POST', '/api/launcher/settings', {'settings': {'voice': True}, 'expected_revision': revision})[0] == 200
    assert request(host, 'POST', '/api/launcher/settings', {'settings': {'voice': False}, 'expected_revision': revision})[0] == 409
    assert request(host, 'POST', '/api/launcher/actions', {'action': 'start'})[0] == 200
    assert request(host, 'POST', '/api/launcher/settings', {'settings': {}, 'expected_revision': host.controller.revision()})[0] == 409


def test_cli_control_and_authenticated_reopen(panel, host, tmp_path):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    channel = LauncherControl(listener, tmp_path / 'data/control' / web_app.CONTROL_FILE_NAME)
    panel.control = channel
    panel.start_worker()
    opened = []
    try:
        assert request_control(channel.path, 'status')['state'] == 'stopped'
        web_app.publish_discovery(tmp_path / 'data/control' / web_app.DISCOVERY_NAME, host, channel)
        assert web_app.reopen_existing(tmp_path, opener=opened.append)
        assert opened == [host.browser_url]
        assert request_control(channel.path, 'start')['ok']
        deadline = time.monotonic() + 3
        while not panel.manager.services and time.monotonic() < deadline:
            time.sleep(.01)
        assert panel.manager.services
        assert request_control(channel.path, 'stop')['ok']
    finally:
        panel.close()
        channel.close()
        listener.close()


def test_legacy_lock_without_new_discovery_never_opens(panel, tmp_path):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    channel = LauncherControl(listener, tmp_path / 'data/control' / web_app.CONTROL_FILE_NAME)
    panel.control = channel
    panel.start_worker()
    opened = []
    try:
        assert not web_app.reopen_existing(tmp_path, opener=opened.append)
        assert not opened
        assert panel.manager.stop_count == 0
    finally:
        panel.close()
        channel.close()
        listener.close()


def test_launcher_phases_are_linked_without_browser_polling(panel):
    request_id = 'a' * 24
    panel.action('start', request_id=request_id)
    panel.perform_pending()
    panel.manager.health = True
    panel.tick()
    rows = panel.events.snapshot()['events']
    assert [row['phase'] for row in rows] == ['ready', 'starting']
    assert all(row['request_id'] == request_id for row in rows)
    panel.action('stop', request_id='b' * 24)
    panel.perform_pending()
    assert panel.events.snapshot()['events'][0]['phase'] == 'stopped'
    assert panel.events.snapshot()['events'][0]['request_id'] == 'b' * 24


def test_launcher_failure_codes_never_copy_exception_body(panel):
    panel.manager.failure = ValueError('synthetic-api-key /private/config and conversation')
    panel.action('start', request_id='a' * 24)
    panel.perform_pending()
    result = panel.events.snapshot()
    assert result['events'][0]['code'] == 'configuration_rejected'
    assert result['events'][0]['request_id'] == 'a' * 24
    assert 'private' not in json.dumps(result)
    assert 'synthetic-api-key' not in panel.snapshot()['message']
    panel.manager.failure = None
    panel.action('start')
    panel.perform_pending()
    panel.started -= 91
    panel.tick()
    assert panel.events.snapshot()['events'][0]['code'] == 'readiness_timeout'


@pytest.mark.parametrize(('error_code', 'code', 'message'), [
    (10049, 'lan_address_unavailable', '此 IP 已不属于本机'),
    (10048, 'port_in_use', '端口已被其他服务占用'),
    (10013, 'bind_denied', '系统拒绝绑定'),
    (99999, 'bind_failed', '绑定检查失败'),
])
def test_launcher_binding_failure_is_actionable_without_raw_exception(panel, error_code, code, message):
    panel.manager.failure = controller.AddressBindingError('192.168.1.22', 8000, error_code)
    panel.action('start', request_id='a' * 24)
    panel.perform_pending()
    snapshot = panel.snapshot()
    assert snapshot['state'] == 'failed' and snapshot['can_start']
    assert message in snapshot['message'] and '192.168.1.22:8000' in snapshot['message']
    assert panel.events.snapshot()['events'][0]['code'] == code
    assert '192.168.1.22' not in json.dumps(panel.events.snapshot())
    assert panel.manager.services == {} and panel.manager.stop_count == 1


def test_readonly_launcher_observability_requires_auth_and_does_not_add_events(host):
    assert request(host, 'GET', '/api/launcher/observability', token=False)[0] == 401
    request(host, 'POST', '/api/launcher/actions', {'action': 'start'})
    host.controller.perform_pending()
    host.controller.manager.health = True
    host.controller.tick()
    code, _, body = request(host, 'GET', '/api/launcher/observability')
    snapshot = json.loads(body)
    assert code == 200 and snapshot['device_playback'] == 'unconfirmed'
    assert snapshot['events'][0]['phase'] == 'ready'
    assert host.token not in body.decode()
    for _ in range(3):
        assert json.loads(request(host, 'GET', '/api/launcher/observability')[2]) == snapshot


def test_launcher_event_rotation_and_write_failure(panel, monkeypatch):
    panel.events.record('a' * 24, event='request_result', action='start')
    panel.events.handler.maxBytes = 220
    for _ in range(70):
        panel.events.record('unsafe-secret', event='request_result', action='private-value')
    paths = list(panel.events.path.parent.glob('launcher-events.jsonl*'))
    assert len(paths) == 3
    assert all('unsafe-secret' not in path.read_text(encoding='utf-8') for path in paths)
    assert len(panel.events.snapshot()['events']) == 50
    monkeypatch.setattr(panel.events.handler, 'shouldRollover', lambda _: (_ for _ in ()).throw(OSError('private-key')))
    panel.events.record('a' * 24, event='request_result', action='stop')
    assert panel.events.snapshot()['persistence'] == 'unavailable'
    assert 'private-key' not in json.dumps(panel.events.snapshot())
