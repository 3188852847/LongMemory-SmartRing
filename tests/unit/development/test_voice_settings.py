import asyncio
import importlib.util
import sys
from pathlib import Path
import pytest

yaml = pytest.importorskip('yaml')
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/development/xiaozhi'))
spec = importlib.util.spec_from_file_location('voice_helper_test', ROOT / 'scripts/development/xiaozhi/voice_settings.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
sys.path.pop(0)


def test_voice_config_only_changes_voice_and_backs_up(tmp_path):
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'data/.config.yaml'
    config = {'prompt': 'synthetic', 'selected_module': {'Memory':'LongMemory', 'TTS':'EdgeTTS'},
              'Memory': {'LongMemory': {'database_path':str(tmp_path / 'test.db'), 'project_root':str(tmp_path)}},
              'TTS': {'EdgeTTS': {'type':'edge', 'voice':module.VOICES[0]}}, 'LLM': {'key':'SYNTHETIC'}}
    path.write_text(yaml.safe_dump(config), encoding='utf-8'); original = path.read_bytes()
    body = {'action':'check', 'database':str(tmp_path / 'test.db'), 'project':str(tmp_path)}
    checked = module.settings(tmp_path, body)
    assert path.read_bytes() == original and len(list(path.parent.iterdir())) == 1
    apply = body | {'action':'apply', 'voice':module.VOICES[1], 'expected_digest':checked['digest']}
    result = module.settings(tmp_path, apply)
    config['TTS']['EdgeTTS']['voice'] = module.VOICES[1]
    assert yaml.safe_load(path.read_bytes()) == config
    assert (path.parent / result['backup']).read_bytes() == original
    with pytest.raises(ValueError): module.settings(tmp_path, apply)
    with pytest.raises(ValueError): module.settings(tmp_path, apply | {'voice':'arbitrary'})
    config['TTS']['EdgeTTS']['private_voice'] = 'override'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    with pytest.raises(ValueError): module.settings(tmp_path, body)


def test_preview_fixed_text_and_size_limit():
    calls = []
    class Fake:
        def __init__(self, text, voice): calls.append((text, voice))
        async def stream(self): yield {'type':'audio', 'data':b'synthetic'}
    assert asyncio.run(module.preview(module.VOICES[0], Fake)) == b'synthetic'
    assert calls == [(module.TEXT, module.VOICES[0])]
    with pytest.raises(ValueError): asyncio.run(module.preview('invalid', Fake))
    class Large(Fake):
        async def stream(self): yield {'type':'audio', 'data':b'x' * (2*1024*1024+1)}
    with pytest.raises(ValueError): asyncio.run(module.preview(module.VOICES[0], Large))
