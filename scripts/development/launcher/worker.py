"""等待父进程确立 Windows Job 所有权后再启动服务。"""

import json
import subprocess
import sys

if __name__ == "__main__":
    line = sys.stdin.buffer.readline(65537)
    if not line or len(line) > 65536:
        raise SystemExit(2)
    command = json.loads(line)
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise SystemExit(2)
    # 不保留第三方输出：其中可能有识别文本、模型响应或私有配置。
    raise SystemExit(subprocess.call(command, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
