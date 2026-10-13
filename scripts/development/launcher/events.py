"""记录启动控制结果与阶段变化；白名单投影避免把配置、凭据和对话写入日志。"""

from datetime import datetime, timezone
import json
from pathlib import Path
import threading


class LauncherEvents:
    def __init__(self, root):
        self.path = Path(root) / 'data/logs/launcher-events.jsonl' if root else None
        self.lock = threading.Lock()
        self.phase = None

    def record(self, request_id, *, event, status=200, action=None, phase=None):
        if self.path is None or event not in {'request_result', 'phase_changed'}:
            return
        body = {'time': datetime.now(timezone.utc).isoformat(),
                'request_id': request_id, 'event': event, 'status': int(status)}
        if action in {'start', 'stop', 'open_console', 'shutdown', 'settings'}:
            body['action'] = action
        if phase in {'stopped', 'starting', 'ready', 'stopping', 'failed'}:
            body['phase'] = phase
        with self.lock:
            if event == 'phase_changed':
                if self.phase == phase:
                    return
                self.phase = phase
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(body, ensure_ascii=False) + '\n')
            except OSError:
                # 日志故障不能使启动控制失效；页面仍从主机实际状态读取事实。
                pass
