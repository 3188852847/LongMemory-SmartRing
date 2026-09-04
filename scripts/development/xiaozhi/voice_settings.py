"""在小智环境中运行；仅操作 EdgeTTS.voice，试听只合成固定文本。"""
import asyncio
import copy
import json
from pathlib import Path
import sys

from sync_role import commit_change, prepare

VOICES = ('zh-CN-XiaoxiaoNeural', 'zh-CN-XiaoyiNeural', 'zh-CN-YunxiNeural', 'zh-CN-YunjianNeural')
TEXT = '你好，很高兴见到你。今天过得怎么样？我们慢慢聊。'


def settings(server, body):
    import yaml
    path = server / 'data/.config.yaml'
    # 复用来源、项目、别名与文件目标检查；不修改角色。
    raw = path.read_bytes()
    before = yaml.safe_load(raw.decode('utf-8'))
    original, _, _ = prepare(path, before.get('prompt'), body['database'], body['project'])
    if original != raw:
        raise ValueError('config_changed')
    if before.get('selected_module', {}).get('TTS') != 'EdgeTTS':
        raise ValueError('unsupported_tts')
    config = before.get('TTS', {}).get('EdgeTTS', {})
    if config.get('type') != 'edge' or config.get('private_voice'):
        raise ValueError('unsupported_tts')
    current = config.get('voice')
    if not isinstance(current, str):
        raise ValueError('invalid_voice')
    voice = current if body['action'] == 'check' else body.get('voice')
    if body['action'] not in {'check', 'apply'} or (body['action'] == 'apply' and voice not in VOICES):
        raise ValueError('invalid_voice')
    text = raw.decode('utf-8'); node = yaml.compose(text)
    for key in ('TTS', 'EdgeTTS', 'voice'):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError('invalid_config')
        keys = [k.value for k, _ in node.value]
        if len(keys) != len(set(keys)) or keys.count(key) != 1:
            raise ValueError('ambiguous_config')
        node = next(v for k, v in node.value if k.value == key)
    if not isinstance(node, yaml.ScalarNode):
        raise ValueError('invalid_voice')
    previous = text[node.start_mark.index:node.end_mark.index]
    replacement = json.dumps(voice)
    if previous.endswith('\n'):
        replacement += '\r\n' if previous.endswith('\r\n') else '\n'
    updated = text[:node.start_mark.index] + replacement + text[node.end_mark.index:]
    expected = copy.deepcopy(before); expected['TTS']['EdgeTTS']['voice'] = voice
    if yaml.safe_load(updated) != expected:
        raise ValueError('unexpected_config_change')
    result = commit_change(path, body, raw, updated.encode('utf-8'), current == voice)
    return result | {'voice': voice, 'voices': list(VOICES), 'text': TEXT}


async def preview(voice, factory=None):
    if voice not in VOICES:
        raise ValueError('invalid_voice')
    if factory is None:
        import edge_tts
        factory = edge_tts.Communicate
    # 不接受任意文本；音频只经过内存，不写入聊天、记忆或音频档案。
    audio = bytearray()
    async for chunk in factory(TEXT, voice=voice).stream():
        if chunk['type'] == 'audio':
            audio.extend(chunk['data'])
            if len(audio) > 2 * 1024 * 1024:
                raise ValueError('audio_too_large')
    if not audio:
        raise ValueError('empty_audio')
    return bytes(audio)


if __name__ == '__main__':
    try:
        body = json.loads(sys.stdin.buffer.read(4096))
        if body.get('action') == 'preview':
            sys.stdout.buffer.write(asyncio.run(asyncio.wait_for(preview(body.get('voice')), 25)))
        else:
            print(json.dumps(settings(Path(sys.argv[1]).resolve(), body)))
    except Exception:
        # 外部库错误不带回私有配置或环境信息。
        raise SystemExit(3)
