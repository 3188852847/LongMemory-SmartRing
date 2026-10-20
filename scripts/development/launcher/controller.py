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
from dataclasses import replace
from uuid import uuid4

from preferences import (
    DEFAULT_SESSION_ALLOW_MEMORY_DELETE, _CHOICES, _PATH_FIELDS,
    load_preferences, save_preferences, load_model_profile, save_model_profile,
    load_memory_backend, save_memory_backend, load_tts_backend, save_tts_backend,
)
from runtime import AddressBindingError, Manager, Options, console_url
from view_model import (
    stopped_services, starting_services, ready_services, failed_services,
    readiness_timeout,
)
from events import LauncherEvents
from voice_ports import validate_voice_ports
from network_watch import NetworkWatch, NetworkSelectionError


class ControllerError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class LauncherController:
    """一个工作线程串行调用 Manager；页面轮询只读取已发布的安全快照。"""

    def __init__(self, root: Path, *, manager=None, opener=webbrowser.open,
                 clock=time.monotonic, readiness_seconds=90, network_watch=None):
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
        self.network_watch = network_watch or NetworkWatch()
        self.network = {'state': 'manual', 'message': '局域网地址使用手动设置。'}
        self.running_revision = None
        self.network_attempted = None
        self.network_restarts = []
        self.network_stopped_owned = False

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
                'network': dict(self.network),
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
                       'memory_backend': {'longmemory', 'hy_memory', 'xiaozhi_local', 'none'}}
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
                elif key in {'voice_ws_port', 'voice_http_port'}:
                    if type(value) is not int:
                        raise ControllerError('圆屏端口必须是整数。')
                elif key == 'lan_interface_id':
                    if value != current[key]:
                        raise ControllerError('网卡身份由本机检测维护，请通过局域网 IP 重新选择。')
                elif type(value) is not bool:
                    raise ControllerError('开关设置必须为布尔值。')
            current.update(values)
            try:
                validate_voice_ports(current['voice_ws_port'], current['voice_http_port'])
            except ValueError as error:
                raise ControllerError(str(error)) from None
            if 'lan_ip' in values:
                current['lan_interface_id'] = ''
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
                       voice_ws_port=values['voice_ws_port'], voice_http_port=values['voice_http_port'],
                       memory_extraction=values['memory_extraction'], memory_retrieval=values['memory_retrieval'],
                       enable_memory_consolidation=values['memory_consolidation'],
                       enable_l1_sufficiency_shadow=values['l1_sufficiency_shadow'],
                       enable_l2_sufficiency_shadow=values['l2_sufficiency_shadow'],
                       embedding_model_dir=Path(values['embedding_model_dir']),
                       sanotts_source_root=Path(values['sanotts_source_root']),
                       tts_backend=values['tts_backend'], vad_profile=values['vad_profile'],
                       model_profile=values['model_profile'], voice_model_profile=values['voice_model_profile'],
                       memory_backend=values['memory_backend'], allow_memory_delete=self.allow_memory_delete)

    def _save_network(self, choice, revision):
        with self._lock:
            if self.revision() != revision:
                raise ValueError('network_preferences_changed')
            values = self.settings()
            if (values['lan_ip'], values['lan_interface_id']) == (choice.address, choice.interface_id):
                return
            path = self.paths['launcher']
            if path.exists():
                # 偏好也留恢复副本；仅在内容变化时写，不把私有路径放进事件。
                backup = self.root / 'local/archive/config-backups' / ('launcher-network-' + uuid4().hex + '.json')
                backup.parent.mkdir(parents=True, exist_ok=True)
                original = path.read_bytes()
                with backup.open('xb') as handle:
                    handle.write(original)
                if hashlib.sha256(backup.read_bytes()).digest() != hashlib.sha256(original).digest():
                    raise ValueError('network_preferences_backup_failed')
            values.update(lan_ip=choice.address, lan_interface_id=choice.interface_id)
            if self.revision() != revision:
                raise ValueError('network_preferences_changed')
            save_preferences(path, values)

    def _network_status(self, state, message, choice=None):
        changed = self.network.get('state') != state
        self.network = {'state': state, 'message': message,
                        **({'address': choice.address} if choice and choice.address else {})}
        if changed:
            self.events.record(self.operation_request_id, event='network_changed', code=state)

    def _start_with_network(self):
        values = self.settings()
        revision = self.revision()
        choice = None
        if values['voice'] and values['network_auto']:
            try:
                choice, _, _ = self.network_watch.observe(values, self.clock(), initial=True)
            except ValueError:
                raise NetworkSelectionError('unavailable') from None
            if choice.state != 'selected':
                raise NetworkSelectionError(choice.state)
        options = self._options()
        if choice:
            options = replace(options, lan_ip=choice.address)
        self.manager.start(options)
        if choice:
            self._save_network(choice, revision)
            self._network_status('network_stable', '电脑网络配置已同步；圆屏保存的连接地址需单独核对。', choice)
        self.running_revision = self.revision()

    def poll_network(self):
        """单工作线程检测；去抖、提示、双端静默租约和Job所有权缺一则不重开。"""
        if self.state not in {'stopped', 'ready'} or self.shutdown_requested.is_set():
            return
        values = self.settings()
        if not values['voice'] or not values['network_auto']:
            return
        revision = self.revision()
        if self.state == 'ready' and revision != self.running_revision:
            self._network_status('network_waiting', '下次启动设置已改变；请先停止服务，再应用网络更新。')
            return
        try:
            observed = self.network_watch.observe(values, self.clock())
        except ValueError:
            self._network_status('network_unavailable', '暂时无法确认物理网卡；保持原服务与配置。')
            return
        if observed is None:
            return
        choice, settled, restart = observed
        if choice.state != 'selected':
            self._network_status('network_ambiguous' if choice.state == 'ambiguous' else 'network_unavailable',
                                 str(NetworkSelectionError(choice.state)))
            return
        if (choice.address, choice.interface_id) == (values['lan_ip'], values['lan_interface_id']):
            self._network_status('network_stable', '正在跟踪已确认的物理网卡；设备连接地址需单独核对。', choice)
            return
        self._network_status('network_waiting', '检测到电脑地址变化，正在等待网络稳定和空闲窗口；请暂缓新聊天。', choice)
        target = (choice.address, choice.interface_id, revision)
        if not settled or target == self.network_attempted:
            return
        with self._lock:
            if (self.state not in {'stopped', 'ready'} or not self._queue.empty()
                    or self.revision() != revision or self.shutdown_requested.is_set()):
                return
            was_running = self.state == 'ready'
            if not was_running and not self.network_stopped_owned:
                self._network_status('network_waiting', '已检测到新地址；首次开启陪伴时会先核对端口再同步，尚未建立服务归属时不自动写配置。', choice)
                return
            if was_running:
                if not restart:
                    return
                self.network_restarts = [stamp for stamp in self.network_restarts if self.clock() - stamp < 3600]
                if len(self.network_restarts) >= 2 or (self.network_restarts and self.clock() - self.network_restarts[-1] < 60):
                    self._network_status('network_waiting', '网络变化过于频繁，已暂停自动重开；请核对网络后手动停止并启动。', choice)
                    return
                if not self.manager.acquire_network_restart():
                    self._network_status('network_waiting', '等待设备断开及网页操作完成；无法确认空闲时保留原服务，可稍后手动停止并启动。', choice)
                    return
            self.network_attempted = target
            self.operation_request_id = secrets.token_hex(12)
            self.operation_started = self.clock()
            self.state = 'stopping' if was_running else 'starting'
            self._phase_event(code='network_restarting')
            self._network_status('network_restarting', '正在安全同步本项目网络；其他应用保持运行。', choice)
        stop_confirmed = not was_running
        try:
            if was_running:
                self.manager.stop()
                stop_confirmed = True
                self.network_restarts.append(self.clock())
                # 停稳后重新枚举，避免在停止期间网卡又变化。
                latest, _, _ = self.network_watch.observe(values, self.clock(), initial=True)
                if latest != choice:
                    raise NetworkSelectionError(latest.state)
            options = replace(self._options(), lan_ip=choice.address)
            if self.revision() != revision:
                raise ValueError('network_preferences_changed')
            if was_running:
                self.manager.start(options)
                self.network_stopped_owned = False
            else:
                self.manager.sync_network_only(options)
            self._save_network(choice, revision)
            self.running_revision = self.revision()
            self.started, self.opened = self.clock(), False
            self.state = 'starting' if was_running else 'stopped'
            self._phase_event(code='network_updated')
            self.presentation = (starting_services(**{key: values[key] for key in (
                'voice', 'voice_mode', 'tts_backend', 'model_profile', 'voice_model_profile', 'memory_backend')})
                if was_running else stopped_services())
            self._network_status('network_updated', '电脑配置已更新；圆屏旧 OTA 地址不会自动改写，请按配网步骤核对。', choice)
        except Exception as error:
            if was_running:
                self.manager.release_network_restart()
            if not stop_confirmed:
                # Job停止不确定时不立即再停一次，也不修改配置或启动新实例。
                self.state = 'failed'
                self.presentation = {**failed_services([]), 'message': '网络更新已暂停：原服务停止未确认，请核对原服务。'}
                self._phase_event(code='stop_unconfirmed')
            else:
                if isinstance(error, (AddressBindingError, NetworkSelectionError)):
                    self._fail(str(error), error.code)
                else:
                    self._fail('网络自动同步未完成；已保留备份，停止自动重试，请核对启动设置。', 'network_update_failed')

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
                self.network_attempted = None
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
                self.network_stopped_owned = False
                self._start_with_network()
                self.started = self.clock()
                self.opened = False
            else:
                had_services = bool(self.manager.services)
                self.manager.stop()
                self.network_stopped_owned = had_services
                with self._lock:
                    self.state, self.presentation, self.opened = 'stopped', stopped_services(), False
                    self.operation_request_id = operation_id
                    self._phase_event()
                if action == 'shutdown':
                    self.shutdown_requested.set()
        except (AddressBindingError, NetworkSelectionError) as error:
            self._fail(str(error), error.code)
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
        elif self.state == 'starting' and self.clock() - self.started > self.readiness_seconds:
            self._fail(readiness_timeout()['message'], 'readiness_timeout')
        elif self.state == 'ready':
            # DHCP变化可能使旧监听暂不可达；不能误套启动超时取消正在处理的会话。
            self.presentation = {'components': {
                key: ('待确认', 'warning') if key in {'console', 'browser'} or options.voice
                else ('本次未启用', 'idle') for key in ('console', 'voice', 'speech', 'browser')},
                'message': '连接状态暂待确认，网络检测仍在进行；可查看圆屏网络提示。'}
            self.manager.publish_status('ready')
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
                try:
                    self.poll_network()
                except Exception:
                    self._network_status('network_unavailable', '网络检测暂不可用，保持原服务；请核对网络状态。')
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
