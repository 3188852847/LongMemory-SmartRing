"""React 启动面板的控制器：复用受管进程，不把 HTTP 线程变成进程所有者。"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
import queue
import secrets
import threading
import time
import webbrowser

from preferences import (
    DEFAULT_SESSION_ALLOW_MEMORY_DELETE, _CHOICES, _PATH_FIELDS,
    load_preferences, save_preferences, load_model_profile, save_model_profile,
    load_memory_backend, save_memory_backend, load_tts_backend, save_tts_backend,
)
from runtime import Manager, Options, console_url
from view_model import (
    stopped_services, starting_services, ready_services, failed_services,
    readiness_timeout,
)
from events import LauncherEvents


class ControllerError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class LauncherController:
    """一个工作线程串行调用 Manager；页面轮询只读取已发布的安全快照。"""

    def __init__(self, root: Path, *, manager=None, opener=webbrowser.open,
                 clock=time.monotonic, readiness_seconds=90):
        self.root = root.resolve()
        self.manager = manager if manager is not None else Manager()
        self.opener, self.clock = opener, clock
        self.readiness_seconds = readiness_seconds
        self.paths = {name: self.root / 'local/config/preferences' / filename for name, filename in (
            ('launcher', 'launcher.json'), ('model', 'model-profile.json'),
            ('memory', 'memory-backend.json'), ('tts', 'tts-backend.json'))}
        self._lock = threading.RLock()
        self._queue = queue.Queue()
        self._closed = threading.Event()
        self.shutdown_requested = threading.Event()
        self.state = 'stopped'
        self.presentation = stopped_services()
        self.opened = False
        self.started = 0.0
        self.allow_memory_delete = DEFAULT_SESSION_ALLOW_MEMORY_DELETE
        self.control = None
        self._thread = None
        self.events = LauncherEvents(self.root)
        self.operation_request_id = None
        self.operation_started = self.clock()

    def settings(self):
        values = load_preferences(self.paths['launcher'])
        for key, default in (
            ('database', self.root / 'data/databases/xiaozhi-demo-v1.db'),
            ('voice_root', self.root / 'local/runtime/xiaozhi-esp32-server/main/xiaozhi-server'),
            ('embedding_model_dir', self.root / 'local/runtime/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620'),
            ('sanotts_source_root', self.root / 'local/runtime/sanoTTS')):
            if not values[key]:
                values[key] = str(default)
        values.update(model_profile=load_model_profile(self.paths['model']),
                      voice_model_profile=load_model_profile(self.paths['model'], 'voice'),
                      memory_backend=load_memory_backend(self.paths['memory']),
                      allow_memory_delete=self.allow_memory_delete)
        values['tts_backend'] = load_tts_backend(self.paths['tts'], values['tts_backend'])
        return values

    def revision(self):
        # 包含共享指针原始字节，使网页同时修改“下次启动”设置可被识别。
        digest = hashlib.sha256()
        for name, path in self.paths.items():
            digest.update(name.encode())
            try:
                digest.update(path.read_bytes())
            except FileNotFoundError:
                digest.update(b'<missing>')
        digest.update(str(self.allow_memory_delete).encode())
        return digest.hexdigest()

    def snapshot(self):
        with self._lock:
            # 外部网页也能写共享指针；不能把旧设置配上新 revision 返回。
            for attempt in range(4):
                try:
                    revision = self.revision()
                    settings = self.settings()
                    if self.revision() == revision:
                        break
                except OSError:
                    raise ControllerError('本机配置暂不可读取，请稍后刷新。', 503) from None
            else:
                raise ControllerError('设置正在其他页面修改，请稍后刷新。', 409)
            return {
                'state': self.state, 'message': self.presentation['message'],
                'services': [{'id': key, 'label': label,
                              'state': self.presentation['components'][key][0],
                              'tone': self.presentation['components'][key][1]}
                             for key, label in (('console', '网页控制台'), ('voice', '小智语音'),
                                                ('speech', '声音服务'), ('browser', '网页入口'))],
                'console_url': (console_url(self.manager.options.port, settings['start_page'])
                                if self.state == 'ready' and self.manager.options else None),
                'settings': settings, 'settings_revision': revision,
                'shutdown_complete': self.shutdown_requested.is_set(),
                'can_start': self.state in {'stopped', 'failed'} and not self.manager.services and not self.shutdown_requested.is_set(),
                'can_stop': self.state in {'starting', 'ready', 'failed'} and bool(self.manager.services),
            }

    def update_settings(self, values, expected_revision):
        with self._lock:
            if self.state in {'starting', 'stopping'} or self.shutdown_requested.is_set():
                raise ControllerError('正在启动或停止，请稍后保存设置。', 409)
            if not isinstance(expected_revision, str) or expected_revision != self.revision():
                raise ControllerError('设置已在其他页面修改，请刷新后重试。', 409)
            current = self.settings()
            if not isinstance(values, dict) or set(values) - set(current):
                raise ControllerError('设置含有不支持的字段。')
            choices = {**_CHOICES, 'model_profile': {'campus', 'official'},
                       'voice_model_profile': {'campus', 'official'},
                       'memory_backend': {'longmemory', 'xiaozhi_local', 'none'}}
            for key, value in values.items():
                if key in _PATH_FIELDS:
                    if value != current[key]:
                        raise ControllerError('资源路径本轮仅供查看，请使用原维护入口修改。')
                elif key in choices:
                    if not isinstance(value, str) or value not in choices[key]:
                        raise ControllerError('设置选项无效。')
                elif key == 'lan_ip':
                    if not isinstance(value, str) or len(value) > 64:
                        raise ControllerError('局域网地址格式无效。')
                    if value:
                        try:
                            address = ipaddress.IPv4Address(value)
                            if not any(address in ipaddress.ip_network(net) for net in
                                       ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
                                raise ValueError
                        except ValueError:
                            raise ControllerError('请输入电脑的局域网 IPv4 地址。') from None
                elif type(value) is not bool:
                    raise ControllerError('开关设置必须为布尔值。')
            current.update(values)
            # 每个 writer 已原子替换；若组合保存失败，恢复此前的原始字节。
            originals = {key: path.read_bytes() if path.exists() else None
                         for key, path in self.paths.items()}
            if expected_revision != self.revision():
                raise ControllerError('设置已在其他页面修改，请刷新后重试。', 409)
            written = {}
            try:
                save_preferences(self.paths['launcher'], current)
                written['launcher'] = self.paths['launcher'].read_bytes()
                save_model_profile(self.paths['model'], current['model_profile'])
                written['model'] = self.paths['model'].read_bytes()
                save_model_profile(self.paths['model'], current['voice_model_profile'], 'voice')
                written['model'] = self.paths['model'].read_bytes()
                save_memory_backend(self.paths['memory'], current['memory_backend'])
                written['memory'] = self.paths['memory'].read_bytes()
                save_tts_backend(self.paths['tts'], current['tts_backend'])
                written['tts'] = self.paths['tts'].read_bytes()
            except OSError:
                for key, published in written.items():
                    path = self.paths[key]
                    if not path.exists() or path.read_bytes() != published:
                        continue  # 别人保存的新值不参与本次回退。
                    body = originals[key]
                    if body is None:
                        path.unlink(missing_ok=True)
                    else:
                        temporary = path.with_suffix('.rollback.tmp')
                        temporary.write_bytes(body)
                        temporary.replace(path)
                raise ControllerError('设置未能完整保存，请检查配置目录。', 500) from None
            self.allow_memory_delete = current['allow_memory_delete']
            return self.snapshot()

    def _options(self):
        values = self.settings()
        return Options(root=self.root, database=Path(values['database']),
                       voice_root=Path(values['voice_root']), voice=values['voice'],
                       voice_mode=values['voice_mode'], voice_latency_mode=values['voice_latency_mode'],
                       lan_ip=values['lan_ip'], role=values['role'], consent=values['http_risk_ack'],
                       memory_extraction=values['memory_extraction'], memory_retrieval=values['memory_retrieval'],
                       enable_memory_consolidation=values['memory_consolidation'],
                       enable_l1_sufficiency_shadow=values['l1_sufficiency_shadow'],
                       enable_l2_sufficiency_shadow=values['l2_sufficiency_shadow'],
                       embedding_model_dir=Path(values['embedding_model_dir']),
                       sanotts_source_root=Path(values['sanotts_source_root']),
                       tts_backend=values['tts_backend'], vad_profile=values['vad_profile'],
                       model_profile=values['model_profile'], voice_model_profile=values['voice_model_profile'],
                       memory_backend=values['memory_backend'], allow_memory_delete=self.allow_memory_delete)

    def action(self, action, *, request_id=None):
        with self._lock:
            if action not in {'start', 'stop', 'open_console', 'shutdown'}:
                raise ControllerError('不支持此操作。')
            if self.shutdown_requested.is_set():
                raise ControllerError('启动面板已退出，请从日常入口重新打开。', 409)
            if self.state == 'stopping' or (self.state == 'starting' and action not in {'stop', 'shutdown'}):
                raise ControllerError('当前操作尚未完成，请稍后重试。', 409)
            if action == 'open_console':
                if self.state != 'ready':
                    raise ControllerError('请先启动并等待控制台就绪。', 409)
                self.opener(self.snapshot()['console_url'])
                self.opened = True
                return self.snapshot()
            if action == 'start':
                if self.manager.services:
                    raise ControllerError('已有受管服务，请先停止。', 409)
                self.state = 'starting'
                settings = self.settings()
                self.presentation = starting_services(**{key: settings[key] for key in (
                    'voice', 'voice_mode', 'tts_backend', 'model_profile', 'voice_model_profile', 'memory_backend')})
            else:
                self.state = 'stopping'
                self.presentation = {**stopped_services(), 'message': '正在停止本面板拥有的服务，请稍候。'}
            operation_id = request_id or secrets.token_hex(12)
            self.operation_request_id = operation_id
            self.operation_started = self.clock()
            self.events.record(operation_id, event='phase_changed', action=action, phase=self.state)
            self._queue.put((action, operation_id, self.operation_started))
            return self.snapshot()

    def _phase_event(self, *, code=None):
        self.events.record(self.operation_request_id, event='phase_changed', phase=self.state,
                           code=code, duration_ms=max(0, round((self.clock() - self.operation_started) * 1000)))

    def _fail(self, message, code='operation_failed'):
        try:
            self.manager.stop()
        except Exception:
            message += ' 停止未完全确认，请勿重复启动；请核对原服务。'
            code = 'stop_unconfirmed'
        with self._lock:
            self.state = 'failed'
            self.presentation = {**failed_services([]), 'message': message}
            self._phase_event(code=code)

    def perform_pending(self):
        """工作线程执行一次操作；测试使用合成 Manager 调用，不接触日用服务。"""
        try:
            action, operation_id, operation_started = self._queue.get_nowait()
        except queue.Empty:
            return
        with self._lock:
            self.operation_request_id = operation_id
            self.operation_started = operation_started
        try:
            if action == 'start':
                self.manager.start(self._options())
                self.started = self.clock()
                self.opened = False
            else:
                self.manager.stop()
                with self._lock:
                    self.state, self.presentation, self.opened = 'stopped', stopped_services(), False
                    self.operation_request_id = operation_id
                    self._phase_event()
                if action == 'shutdown':
                    self.shutdown_requested.set()
        except ValueError:
            self._fail('受管服务配置检查未通过，请核对启动设置与恢复指南。', 'configuration_rejected')
        except Exception:
            self._fail('无法完成受管服务操作。未关闭外部程序；请查看启动指南。')

    def tick(self):
        if self.state not in {'starting', 'ready'} or not self.manager.services:
            return
        options = self.manager.options
        exited = [(name, service.process.poll()) for name, service in self.manager.services.items()
                  if service.process.poll() is not None]
        if exited:
            self._fail(failed_services(exited, options.tts_backend, options.voice_mode)['message'], 'child_exited')
        elif self.manager.ready():
            local_ready = (self.manager.local_tts_ready() if options.voice and options.voice_mode == 'pipeline'
                           and options.tts_backend in {'voxcpm2', 'sanotts', 'cosyvoice3'} else False)
            with self._lock:
                if self.state not in {'starting', 'ready'}:
                    return
                self.state = 'ready'
                self._phase_event()
                self.presentation = ready_services(voice=options.voice, voice_mode=options.voice_mode,
                    tts_backend=options.tts_backend, local_tts_ready=local_ready, opened=self.opened)
            self.manager.publish_status('ready', console_ready=True, voice_ready=options.voice, tts_ready=local_ready)
        elif self.clock() - self.started > self.readiness_seconds:
            self._fail(readiness_timeout()['message'], 'readiness_timeout')
        else:
            self.manager.publish_status('starting')

    def dispatch_control(self, action):
        """原 CLI 仍保留 ok/state/ready/selection；HTTP 独立使用新的五状态模型。"""
        if action == 'status':
            snapshot = self.snapshot()
            return {'ok': True, 'state': 'running' if self.manager.services else 'stopped',
                    'ready': snapshot['state'] == 'ready',
                    'selection': {key: value for key, value in snapshot['settings'].items()
                                  if key not in _PATH_FIELDS and key != 'lan_ip' and key != 'http_risk_ack'}}
        if action == 'start' and self.manager.services:
            return {'ok': True, 'state': 'already_running'}
        if action == 'stop' and not self.manager.services and self.state != 'starting':
            return {'ok': True, 'state': 'already_stopped'}
        try:
            result = self.action(action)
            # 原 socket 客户端的 stop 返回已停止事实；长操作超时仍沿用
            # LauncherControl 的“已运行结果未知”语义，不假称失败后再执行。
            self.perform_pending()
            failed = self.state == 'failed'
            return {'ok': not failed, 'state': action + '_failed' if failed else
                    ('stopped' if action == 'stop' else 'starting')}
        except ControllerError:
            return {'ok': False, 'state': action + '_failed'}

    def run(self):
        while not self._closed.wait(.25):
            try:
                if self.control:
                    self.control.poll(self.dispatch_control)
                self.perform_pending()
                self.tick()
            except Exception:
                self._fail('服务状态检查失败，已尝试停止本面板拥有的服务。请查看启动指南。', 'health_check_failed')

    def start_worker(self):
        self._thread = threading.Thread(target=self.run, name='launcher-manager', daemon=True)
        self._thread.start()

    def close(self):
        self._closed.set()
        if self._thread:
            self._thread.join()
        try:
            self.manager.stop()
        finally:
            self.events.close()
