"""物理网卡、独立端口和受管切换验收；仅合成配置与替身，不访问日用服务。"""

from dataclasses import replace
import json
from pathlib import Path
import sys
import socket
from types import SimpleNamespace

import pytest

DIRECTORY = Path(__file__).resolve().parents[3] / 'scripts/development/launcher'
sys.path.insert(0, str(DIRECTORY))
try:
    from controller import LauncherController
    from network_watch import NetworkWatch, choose_address, NetworkSelectionError
    from preferences import save_preferences, load_preferences
    from voice_ports import validate_voice_ports
    import runtime
    from sync_network import sync
finally:
    sys.path.pop(0)

A = '11111111-1111-1111-1111-111111111111'
B = '22222222-2222-2222-2222-222222222222'


def adapter(address='192.168.1.2', identity=A, **kwargs):
    return dict(address=address, interface_id=identity, physical=True, up=True, preferred=True, **kwargs)


def test_physical_selection_pins_identity_and_never_fails_over_to_other_adapter():
    assert choose_address([adapter()]).address == '192.168.1.2'
    assert choose_address([adapter(), adapter('10.1.2.3', B)]).state == 'ambiguous'
    assert choose_address([adapter(), adapter('10.1.2.3', B)], '192.168.1.2').interface_id == A
    assert choose_address([adapter('192.168.1.4'), adapter('10.1.2.3', B)], '192.168.1.2', A).address == '192.168.1.4'
    assert choose_address([adapter('10.1.2.3', B)], '192.168.1.2', A).state == 'offline'
    assert choose_address([adapter(), adapter('192.168.1.4')], '', A).state == 'ambiguous'
    assert choose_address([], '', 'malformed').state == 'ambiguous'


@pytest.mark.parametrize('address', ['127.0.0.1', '100.64.164.2', '169.254.1.2', '8.8.8.8', '::1', '0.0.0.0'])
def test_unusable_addresses_are_excluded(address):
    assert choose_address([adapter(address)]).state == 'offline'


@pytest.mark.parametrize('field', ['physical', 'up', 'preferred'])
def test_virtual_disconnected_or_deprecated_candidate_is_excluded(field):
    row = adapter()
    row[field] = False
    assert choose_address([row]).state == 'offline'


@pytest.mark.parametrize('ports', [(True, 18003), ('18000', 18003), (18000, 18000), (8766, 18003),
                                  (18770, 18003), (1023, 18003), (65536, 18003)])
def test_ports_reject_invalid_pairs(ports):
    with pytest.raises(ValueError):
        validate_voice_ports(*ports)


def test_port_sync_is_reversible_and_preserves_other_configuration(tmp_path):
    yaml = pytest.importorskip('yaml')
    original = ('server:\n  ip: 192.168.1.2\n  port: 8000\n  http_port: 8003\n'
                '  websocket: ws://192.168.1.2:8000/xiaozhi/v1/\n'
                '  vision_explain: http://192.168.1.2:8003/mcp/vision/explain\n'
                'selected_module:\n  LLM: CampusLLM\nLLM:\n  api_key: synthetic-secret\n'
                'prompt: |\n  keep synthetic role and voice\n')
    path = tmp_path / '.config.yaml'
    path.write_text(original, encoding='utf-8')
    assert sync(path, '192.168.1.4', True, 18000, 18003)['changed']
    changed = path.read_text(encoding='utf-8')
    assert 'port: 18000' in changed and 'http_port: 18003' in changed
    assert 'ws://192.168.1.4:18000/' in changed and 'http://192.168.1.4:18003/' in changed
    assert original[original.index('selected_module:'):] == changed[changed.index('selected_module:'):]
    assert next(tmp_path.glob('*.bak')).read_text(encoding='utf-8') == original
    assert not sync(path, '192.168.1.4', True, 18000, 18003)['changed']
    sync(path, '192.168.1.2', True)
    # 网络字符串由既有同步器规范为JSON引号；比较网络语义，其余字节上面单独核对。
    assert yaml.safe_load(path.read_text(encoding='utf-8')) == yaml.safe_load(original)


def test_network_sync_rejects_stale_digest_before_backup_or_write(tmp_path):
    path = tmp_path / '.config.yaml'
    original = b'server:\n  ip: 192.168.1.2\n'
    path.write_bytes(original)
    with pytest.raises(ValueError, match='changed since network check'):
        sync(path, '192.168.1.4', True, 18000, 18003, '0' * 64)
    assert path.read_bytes() == original and list(tmp_path.iterdir()) == [path]


class Manager:
    def __init__(self):
        self.options = None
        self.services = {}
        self.calls = []
        self.lease = True
        self.stop_error = False
        self.on_lease = lambda: None

    def start(self, options):
        assert not self.services
        self.options = options
        self.calls.append(('start', options.lan_ip, options.voice_ws_port, options.voice_http_port))
        self.services['voice'] = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))

    def stop(self):
        self.calls.append(('stop',))
        if self.stop_error:
            raise RuntimeError('synthetic stop uncertainty')
        self.services.clear()

    def ready(self): return bool(self.services)
    def local_tts_ready(self): return True
    def publish_status(self, *_args, **_kwargs): pass
    def acquire_network_restart(self):
        self.on_lease()
        self.calls.append(('lease',))
        return self.lease
    def release_network_restart(self): self.calls.append(('release',))
    def sync_network_only(self, options): self.calls.append(('sync', options.lan_ip))


@pytest.fixture
def system(tmp_path):
    now = [0.0]
    rows = [adapter()]
    manager = Manager()
    path = tmp_path / 'local/config/preferences/launcher.json'
    save_preferences(path, dict(voice=True, network_auto=True, voice_ws_port=18000, voice_http_port=18003,
                                lan_ip='192.168.1.2', lan_interface_id=A))
    panel = LauncherController(tmp_path, manager=manager, clock=lambda: now[0],
                               network_watch=NetworkWatch(discover=lambda: list(rows), interval=5))
    yield panel, manager, path, rows, now
    panel.events.close()


def start(system):
    panel, manager, path, rows, now = system
    panel.action('start')
    panel.perform_pending()
    panel.tick()
    assert panel.state == 'ready'


def poll(system, seconds):
    panel, manager, path, rows, now = system
    now[0] += seconds
    panel.poll_network()


def test_lost_address_is_automatically_corrected_and_pinned_before_start(system):
    panel, manager, path, rows, now = system
    rows[:] = [adapter('192.168.1.4')]
    start(system)
    assert manager.options.lan_ip == '192.168.1.4'
    assert load_preferences(path)['lan_ip'] == '192.168.1.4'
    assert len(list((panel.root / 'local/archive/config-backups').glob('*.json'))) == 1
    assert manager.options.voice_ws_port == 18000 and manager.options.voice_http_port == 18003


def test_runtime_defers_while_busy_then_restarts_exactly_once(system):
    panel, manager, path, rows, now = system
    start(system)
    manager.lease = False
    rows[:] = [adapter('192.168.1.4')]
    before = path.read_bytes()
    poll(system, 5)
    poll(system, 10)
    assert ('lease',) not in manager.calls
    poll(system, 10)
    assert path.read_bytes() == before and ('stop',) not in manager.calls
    manager.lease = True
    poll(system, 5)
    assert manager.calls[-2:] == [('stop',), ('start', '192.168.1.4', 18000, 18003)]
    assert panel.state == 'starting' and load_preferences(path)['lan_ip'] == '192.168.1.4'
    panel.tick()
    poll(system, 10)
    assert sum(call[0] == 'start' for call in manager.calls) == 2


def test_disconnect_does_not_write_or_restart_and_recovery_resumes(system):
    panel, manager, path, rows, now = system
    start(system)
    before = path.read_bytes()
    rows.clear()
    poll(system, 5)
    poll(system, 30)
    assert panel.network['state'] == 'network_unavailable'
    assert path.read_bytes() == before and ('stop',) not in manager.calls
    rows[:] = [adapter('192.168.1.4')]
    poll(system, 5)
    poll(system, 20)
    assert load_preferences(path)['lan_ip'] == '192.168.1.4'


def test_stopped_sync_debounces_and_does_not_launch_services(system):
    panel, manager, path, rows, now = system
    start(system)
    panel.action('stop')
    panel.perform_pending()
    before_calls = list(manager.calls)
    rows[:] = [adapter('192.168.1.4')]
    poll(system, 0)
    poll(system, 5)
    assert manager.calls == before_calls
    poll(system, 5)
    poll(system, 20)
    assert manager.calls == before_calls + [('sync', '192.168.1.4')]
    assert panel.state == 'stopped' and load_preferences(path)['lan_ip'] == '192.168.1.4'


def test_initial_stopped_detection_does_not_write_without_established_ownership(system):
    panel, manager, path, rows, now = system
    before = path.read_bytes()
    rows[:] = [adapter('192.168.1.4')]
    poll(system, 0)
    poll(system, 30)
    assert path.read_bytes() == before and manager.calls == []
    assert panel.network['state'] == 'network_waiting'


def test_external_settings_change_is_never_overwritten_or_automatically_applied(system):
    panel, manager, path, rows, now = system
    start(system)
    values = load_preferences(path)
    values['voice_ws_port'] = 19000
    save_preferences(path, values)
    before = path.read_bytes()
    rows[:] = [adapter('192.168.1.4')]
    poll(system, 30)
    assert path.read_bytes() == before and ('stop',) not in manager.calls
    assert panel.network['state'] == 'network_waiting'


def test_failed_switch_is_latched_without_repeated_auto_attempts(system):
    panel, manager, path, rows, now = system
    start(system)
    rows[:] = [adapter('192.168.1.4')]
    manager.stop_error = True
    poll(system, 5)
    poll(system, 20)
    count = len(manager.calls)
    poll(system, 100)
    assert panel.state == 'failed' and len(manager.calls) == count
    assert load_preferences(path)['lan_ip'] == '192.168.1.2'


def test_ambiguous_initial_selection_fails_before_start(system):
    panel, manager, path, rows, now = system
    values = load_preferences(path)
    values.update(lan_ip='192.168.1.99', lan_interface_id='')
    save_preferences(path, values)
    rows[:] = [adapter(), adapter('10.1.2.3', B)]
    panel.action('start')
    panel.perform_pending()
    assert panel.state == 'failed' and not any(call[0] == 'start' for call in manager.calls)
    assert panel.events.snapshot()['events'][0]['code'] == 'network_ambiguous'


def test_manager_refuses_unowned_or_dead_services_without_lease_http(monkeypatch):
    manager = runtime.Manager()
    manager.options = runtime.Options(voice=True)
    manager.services = {'unknown': SimpleNamespace(process=SimpleNamespace(poll=lambda: None))}
    monkeypatch.setattr(manager, '_maintenance', lambda **_: pytest.fail('must not contact unknown owner'))
    assert manager.acquire_network_restart() is False


def test_manager_takes_both_leases_or_releases_without_stopping(monkeypatch):
    manager = runtime.Manager()
    manager.options = runtime.Options(voice=True)
    service = object.__new__(runtime.OwnedService)
    service.job = SimpleNamespace(handle=object())
    service.process = SimpleNamespace(poll=lambda: None)
    manager.services = {'voice': service}
    calls = []
    def maintenance(*, voice, draining):
        calls.append((voice, draining))
        return voice or not draining
    monkeypatch.setattr(manager, '_maintenance', maintenance)
    assert manager.acquire_network_restart() is False
    assert calls == [(True, True), (False, True), (False, False), (True, False)]
    assert manager.services == {'voice': service}


def test_rapid_second_change_waits_for_cooldown(system):
    panel, manager, path, rows, now = system
    start(system)
    rows[:] = [adapter('192.168.1.4')]
    poll(system, 5)
    poll(system, 20)
    panel.tick()
    rows[:] = [adapter('192.168.1.5')]
    poll(system, 5)
    poll(system, 20)
    assert sum(call[0] == 'start' for call in manager.calls) == 2
    assert load_preferences(path)['lan_ip'] == '192.168.1.4'


def test_network_events_never_include_address_or_adapter_identity(system):
    panel, manager, path, rows, now = system
    rows.clear()
    poll(system, 0)
    assert panel.network['state'] == 'network_unavailable'
    data = json.dumps(panel.events.snapshot())
    assert A not in data and '192.168.' not in data


def test_ready_health_loss_is_not_mistaken_for_initial_start_timeout(system):
    panel, manager, path, rows, now = system
    start(system)
    manager.ready = lambda: False
    now[0] += 100
    panel.tick()
    assert panel.state == 'ready' and manager.services
    assert ('stop',) not in manager.calls
    assert all('停止' not in label for label, tone in panel.presentation['components'].values())


def test_discovery_is_periodic_and_does_not_run_per_tick_or_turn():
    calls = []
    watch = NetworkWatch(discover=lambda: calls.append(1) or [adapter()])
    values = {'lan_ip': '192.168.1.2', 'lan_interface_id': A}
    watch.observe(values, 0)
    for tick in (0.25, 1, 5, 10, 20, 29):
        assert watch.observe(values, tick) is None
    assert len(calls) == 1
    watch.observe(values, 30)
    assert len(calls) == 2


def test_two_port_pairs_coexist_and_manager_only_preflights_selected_pair(tmp_path, monkeypatch):
    listeners = []
    try:
        for _ in range(4):
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            listener.listen(2)
            listeners.append(listener)
        external_ports = [item.getsockname()[1] for item in listeners[:2]]
        own_ports = [item.getsockname()[1] for item in listeners[2:]]
        for listener in listeners[2:]:
            listener.close()
        selected = runtime.Options(root=tmp_path, voice_root=tmp_path / 'synthetic-voice', voice=True,
                                   lan_ip='127.0.0.1', tts_backend='edge',
                                   voice_ws_port=own_ports[0], voice_http_port=own_ports[1])
        checked, network_calls = [], []
        original = runtime.require_free
        def preflight(host, port):
            checked.append((host, port))
            if port in own_ports:
                original(host, port)
        def network_action(server, address, **kwargs):
            network_calls.append(kwargs)
            assert kwargs['ws_port'] == own_ports[0] and kwargs['http_port'] == own_ports[1]
            return {'changed': False, 'digest': 'a' * 64}
        monkeypatch.setattr(runtime, 'build_commands', lambda _: [])
        monkeypatch.setattr(runtime, 'require_free', preflight)
        monkeypatch.setitem(sys.modules, 'network', SimpleNamespace(config_action=network_action))
        for name in ('tts', 'model', 'memory', 'vad'):
            monkeypatch.setitem(sys.modules, name, SimpleNamespace(config_action=lambda *a, **k: {'config_matches': True}))
        manager = runtime.Manager()
        manager.start(selected)
        manager.stop()
        assert all(('127.0.0.1', port) in checked for port in own_ports)
        assert all(port not in {8000, 8003, *external_ports} for host, port in checked)
        assert len(network_calls) == 1
        for listener in listeners[:2]:
            with socket.create_connection(listener.getsockname(), timeout=1):
                connection, _ = listener.accept()
                connection.close()
    finally:
        for listener in listeners:
            listener.close()
