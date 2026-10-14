"""用确定性替身运行真实启动器 HTTP 主机，不读取配置、不创建服务或个人库。"""

import json
from pathlib import Path
import sys
import threading
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/development/launcher'))
from controller import ControllerError
from preferences import DEFAULTS
from web_app import create_server
from events import LauncherEvents


class PreviewController:
    """仅模拟启动器状态；所有进程、声音与设备事实都明确属于合成替身。"""

    def __init__(self, root=None):
        self.lock = threading.RLock()
        self.events = LauncherEvents(root)
        self.settings = {**DEFAULTS, 'model_profile': 'official',
                         'voice_model_profile': 'official', 'memory_backend': 'longmemory',
                         'memory_extraction': 'llm', 'memory_retrieval': 'hybrid'}
        self.state = 'stopped'
        self.version = 1
        self.complete = False
        self.pending = 0

    def snapshot(self):
        with self.lock:
            if self.pending:
                self.pending -= 1
                if not self.pending:
                    self.state = 'ready' if self.state == 'starting' else 'stopped'
            ready = self.state == 'ready'
            return {'state': self.state, 'message': '合成测试服务状态，不连接真实圆屏。',
                    'services': [{'id': 'console', 'label': '网页控制台',
                                  'state': '测试服务已就绪' if ready else '尚未启动',
                                  'tone': 'good' if ready else 'idle'},
                                 {'id': 'voice', 'label': '小智语音', 'state': '本次不启动', 'tone': 'idle'},
                                 {'id': 'speech', 'label': '声音服务', 'state': '本次不启动', 'tone': 'idle'},
                                 {'id': 'browser', 'label': '网页入口', 'state': '测试入口', 'tone': 'idle'}],
                    'settings': dict(self.settings), 'settings_revision': f'preview-{self.version}',
                    'console_url': 'http://127.0.0.1:18777/chat-react' if ready else None,
                    'can_start': self.state == 'stopped', 'can_stop': ready,
                    'shutdown_complete': self.complete}

    def update_settings(self, settings, expected_revision):
        with self.lock:
            if expected_revision != f'preview-{self.version}':
                raise ControllerError('设置已在其他页面修改，请刷新后重试。', 409)
            self.settings.update(settings)
            self.version += 1
            return self.snapshot()

    def action(self, action, *, request_id=None):
        with self.lock:
            if action == 'start':
                self.state, self.pending = 'starting', 3
            elif action in {'stop', 'shutdown'}:
                self.state, self.pending = 'stopping', 3
            elif action != 'open_console':
                raise ControllerError('不支持此操作。')
            return self.snapshot()


if __name__ == '__main__':
    with TemporaryDirectory(prefix='launcher-preview-') as directory:
        preview = PreviewController(Path(directory))
        server = create_server(preview, ROOT / 'web/react-chat/dist',
                               token='synthetic-launcher-browser-test-token')
        print(json.dumps({'origin': server.origin}), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            preview.events.close()
