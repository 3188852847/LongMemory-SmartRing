"""记录启动控制结果与阶段变化；白名单投影避免把配置、凭据和对话写入日志。"""

from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import secrets
import threading
from collections import deque


class SafeRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        raise OSError('launcher_event_write_failed') from None


class LauncherEvents:
    def __init__(self, root):
        self.path = Path(root) / 'data/logs/launcher-events.jsonl' if root else None
        self.lock = threading.Lock()
        self.phase = None
        self.recent = deque(maxlen=50)
        self.write_failed = False
        self.handler = None

    def record(self, request_id, *, event, status=200, action=None, phase=None,
               code=None, duration_ms=None, initial_only=False):
        if self.path is None or event not in {'request_result', 'phase_changed'}:
            return
        # 请求 ID 只接受服务端的固定十六进制格式，拒绝把任意字符串落盘。
        if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{24}', request_id):
            request_id = secrets.token_hex(12)
        body = {'time': datetime.now(timezone.utc).isoformat(),
                'request_id': request_id, 'event': event, 'status': int(status)}
        if action in {'start', 'stop', 'open_console', 'shutdown', 'settings'}:
            body['action'] = action
        if phase in {'stopped', 'starting', 'ready', 'stopping', 'failed'}:
            body['phase'] = phase
        if code in {'operation_failed', 'configuration_rejected', 'readiness_timeout',
                    'child_exited', 'health_check_failed', 'stop_unconfirmed'}:
            body['code'] = code
        if isinstance(duration_ms, int) and duration_ms >= 0:
            body['duration_ms'] = duration_ms
        with self.lock:
            if initial_only and self.phase is not None:
                return
            if event == 'phase_changed':
                if self.phase == phase:
                    return
                self.phase = phase
            self.recent.append(body)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.handler is None:
                    self.handler = SafeRotatingHandler(self.path, maxBytes=1024 * 1024,
                                                       backupCount=2, encoding='utf-8')
                    self.handler.setFormatter(logging.Formatter('%(message)s'))
                record = logging.LogRecord('launcher.events', logging.INFO, '', 0,
                                           json.dumps(body, ensure_ascii=False), (), None)
                if self.handler.shouldRollover(record):
                    self.handler.doRollover()
                logging.FileHandler.emit(self.handler, record)
            except OSError:
                # 日志故障不能使启动控制失效；页面仍从主机实际状态读取事实。
                self.write_failed = True

    def snapshot(self):
        with self.lock:
            return {'schema_version': 1, 'scope': 'launcher_process',
                    'events': [dict(row) for row in reversed(self.recent)],
                    'persistence': 'unavailable' if self.write_failed else 'enabled',
                    'retention': {'max_bytes': 1024 * 1024, 'backups': 2},
                    'device_playback': 'unconfirmed'}

    def close(self):
        with self.lock:
            if self.handler:
                self.handler.close()
