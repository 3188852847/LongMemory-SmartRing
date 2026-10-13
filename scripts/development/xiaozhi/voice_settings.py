"""在小智环境中读取声音后端；仅 EdgeTTS 支持音色修改与固定文本试听。"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from config_paths import config_path
import sys

from sync_role import commit_change, prepare

VOICES = ('zh-CN-XiaoxiaoNeural', 'zh-CN-XiaoyiNeural', 'zh-CN-YunxiNeural', 'zh-CN-YunjianNeural')
TEXT = '你好，很高兴见到你。今天过得怎么样？我们慢慢聊。'
VOX_URL = 'http://127.0.0.1:18768/v1/audio/speech'
SANO_URL = 'http://127.0.0.1:18769/v1/audio/speech'
COSY_URL = 'http://127.0.0.1:18770/v1/audio/speech'


def _custom_contract(config, url):
    custom = config.get('TTS', {}).get('CustomTTS', {})
    params = custom.get('params', {}) if isinstance(custom, dict) else {}
    return (isinstance(custom, dict) and custom.get('type') == 'custom'
            and custom.get('method') == 'POST' and custom.get('url') == url
            and custom.get('format') == 'wav' and isinstance(params, dict)
            and params.get('input') == '{prompt_text}'
            and params.get('response_format') == 'wav' and params.get('stream') is False)


def _sanotts_speed(params):
    """旧配置没有 speed 时按上游默认 1.0 解释，不强迫用户重新同步。"""
    value = params.get('speed', 1.0)
    if type(value) not in {int, float} or not 0.75 <= value <= 1.5:
        raise ValueError('invalid_speed')
    return float(value)


def _update_sanotts_speed(text, before, speed, yaml):
    """只替换或插入 speed 标量，保留私有 YAML 的其余原始字节。"""
    root = yaml.compose(text)
    node = root
    for key in ('TTS', 'CustomTTS', 'params'):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError('ambiguous_config')
        matches = [value for candidate, value in node.value if candidate.value == key]
        if len(matches) != 1:
            raise ValueError('ambiguous_config')
        node = matches[0]
    if not isinstance(node, yaml.MappingNode):
        raise ValueError('ambiguous_config')

    speed_nodes = [(key, value) for key, value in node.value if key.value == 'speed']
    if len(speed_nodes) > 1:
        raise ValueError('ambiguous_config')
    scalar = str(speed)
    if speed_nodes:
        value = speed_nodes[0][1]
        if not isinstance(value, yaml.ScalarNode):
            raise ValueError('ambiguous_config')
        updated = text[:value.start_mark.index] + scalar + text[value.end_mark.index:]
    else:
        # PyYAML 把下一个同级字段的前导空格计入 MappingNode 范围。先退回到
        # 当前行开头，再插入完整新行，后缀中的四个空格继续属于下一个字段。
        insertion_at = node.end_mark.index - node.end_mark.column
        newline = '\r\n' if '\r\n' in text else '\n'
        insertion = '      speed: ' + scalar + newline
        updated = text[:insertion_at] + insertion + text[insertion_at:]
    expected = copy.deepcopy(before)
    expected['TTS']['CustomTTS']['params']['speed'] = speed
    if yaml.safe_load(updated) != expected:
        raise ValueError('unexpected_config_change')
    return updated.encode('utf-8')


def settings(server, body):
    import yaml
    path = config_path(server)
    # 复用来源、项目、别名与文件目标检查；不修改角色。
    raw = path.read_bytes()
    before = yaml.safe_load(raw.decode('utf-8'))
    original, _, _ = prepare(path, before.get('prompt'), body['database'], body['project'])
    if original != raw:
        raise ValueError('config_changed')
    selected = before.get('selected_module', {}).get('TTS')
    digest = hashlib.sha256(raw).hexdigest()
    if selected == 'CustomTTS':
        custom_url = before.get('TTS', {}).get('CustomTTS', {}).get('url')
        backend, voice = ({VOX_URL: ('voxcpm2', 'plain'), SANO_URL: ('sanotts', 'xiaoya'),
                           COSY_URL: ('cosyvoice3', 'official-zero-shot')}
                          .get(custom_url, ('unsupported', None)))
        params = before.get('TTS', {}).get('CustomTTS', {}).get('params', {})
        speed = _sanotts_speed(params) if backend == 'sanotts' else None
        if body.get('action') == 'apply_sanotts' and backend == 'sanotts':
            requested = body.get('speed')
            if type(requested) not in {int, float} or not 0.75 <= requested <= 1.5:
                raise ValueError('invalid_speed')
            updated = _update_sanotts_speed(raw.decode('utf-8'), before,
                                             float(requested), yaml)
            result = commit_change(path, body, raw, updated, speed == float(requested),
                                   backup_label='tts')
            return result | {'backend': backend, 'voice': voice, 'voices': [],
                             'digest': hashlib.sha256(updated).hexdigest(), 'text': TEXT,
                             'config_matches': True, 'editable': True,
                             'speed': float(requested)}
        if body.get('action') != 'check':
            raise ValueError('unsupported_tts_operation')
        return {'backend': backend, 'voice': voice, 'voices': [], 'digest': digest,
                'text': TEXT, 'config_matches': _custom_contract(before, custom_url)
                if backend != 'unsupported' else False, 'editable': backend == 'sanotts',
                **({'speed': speed} if speed is not None else {})}
    if selected != 'EdgeTTS':
        if body.get('action') != 'check':
            raise ValueError('unsupported_tts_operation')
        return {'backend': 'unsupported', 'voice': None, 'voices': [], 'digest': digest,
                'text': TEXT, 'config_matches': False, 'editable': False}
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
    return result | {'backend': 'edge', 'voice': voice, 'voices': list(VOICES), 'text': TEXT,
                     'config_matches': True, 'editable': True, 'service_ready': None}


async def preview(voice, text=TEXT, factory=None):
    if voice not in VOICES:
        raise ValueError('invalid_voice')
    # 保留旧测试/调用方的 preview(voice, factory) 兼容入口。
    if callable(text) and factory is None:
        factory, text = text, TEXT
    if factory is None:
        import edge_tts
        factory = edge_tts.Communicate
    if not isinstance(text, str) or not text.strip() or len(text) > 600:
        raise ValueError('invalid_text')
    # 音频只经过内存，不写入聊天、记忆或音频档案。
    audio = bytearray()
    async for chunk in factory(text.strip(), voice=voice).stream():
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
            sys.stdout.buffer.write(asyncio.run(asyncio.wait_for(preview(body.get('voice'), body.get('text', TEXT)), 30)))
        else:
            print(json.dumps(settings(Path(sys.argv[1]).resolve(), body)))
    except Exception:
        # 外部库错误不带回私有配置或环境信息。
        raise SystemExit(3)
