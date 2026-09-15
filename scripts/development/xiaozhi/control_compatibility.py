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
    # 提前听写依赖 PCM、正式端点及重置顺序；上游变化后先复核，不能继续复用旧候选。
    "core/providers/asr/base.py": "929532c379d18598eff6fbecb991089f25a0c62cd77f74a25a0d1a5b8d13a713",
    "core/providers/asr/fun_local.py": "1f8df28ee5f0a1dd23948211e92c2caddf0d440191f7d0b82b2b0e13788ebf6a",
    "core/providers/asr/utils.py": "64db7ba4523d494b27e8b25bd84261ec1fcfee6816b4720d84776cda4e7cedcf",
    "core/providers/vad/silero.py": "aa375cd237c262338b391f8826f35bfe9b3c9e4c77a197bfe75490806d825114",
    "core/handle/receiveAudioHandle.py": "4493dfd77c1bfa7be1a79bb293dbdbf8cad64a6eb2bc53efca3e30efefcb47f1",
    "core/handle/textHandler/listenMessageHandler.py": "4337bf92e55adeafbd0bf3411b59b74cadf1561bac47ef96e6b80c02d0d1dd3c",
    "core/providers/llm/openai/openai.py": "5dfec38041d28436362b4a1b0f5946d1bdff7bb9afb3501c6417037a6bd3b006",
}


def verify_control_snapshot(root):
    for name, expected in EXPECTED.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"设备控制暂不支持该文件版本：{name}；需重新审查，不自动覆盖上游。")
