"""控制包装依赖具体连接生命周期；上游变更后必须重新审查，而非盲目套用。"""

import hashlib


# 当前本地已审查文件的字节哈希。不是对上游整个仓库的完整性或安全背书。
EXPECTED = {
    "core/connection.py": "e065c994bf3f926b81c69da045e09fad8c46d6fd1fc3e3a6403295aeab64e0fa",
    "core/websocket_server.py": "5d131587954c611a8ee374f2c0e12065e9d25fe469b8fa96778767e48803a426",
    "core/handle/helloHandle.py": "77be3faf5c8201450f1b98c51140a8960155a9bf95f67dfc288768ba14857d51",
    "core/providers/tools/device_mcp/mcp_handler.py": "05e1cb5b7fe1cd2e7219ccc3445cd5f6af5ec5344b532d65f659e32c0394e1dc",
    "core/providers/tools/device_mcp/mcp_client.py": "f0df40319be70ec87bccfcc7a6c758bae9ad712e01682c0c8c8da74809dfa4c5",
    "core/handle/sendAudioHandle.py": "6b610cc04bf05a75964f5fe668bfda7fd17b087ef8f2a938e1bc8ed9b0c52387",
    "core/providers/tts/base.py": "8c9c6d9da3774d2f78d05e5d0e7c5081d750752466f36a593733911430bac00f",
    "core/providers/tts/dto/dto.py": "6ba9742e4778bcd31980f1f9347d20aecbed065f152735ef407516b7b70d756c",
}


def verify_control_snapshot(root):
    for name, expected in EXPECTED.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"设备控制暂不支持该文件版本：{name}；需重新审查，不自动覆盖上游。")
