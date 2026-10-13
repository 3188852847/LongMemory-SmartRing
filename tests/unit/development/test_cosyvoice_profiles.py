"""合成 PCM 验证私有声线档案，不读取真实音频，不加载模型。"""
import importlib.util
from io import BytesIO
import json
import os
import subprocess
from pathlib import Path
import threading
from types import SimpleNamespace
import wave

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('voice_profile_test', ROOT / 'scripts/development/cosyvoice/voice_profiles.py')
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)


def pcm(seconds=3):
    result = BytesIO()
    with wave.open(result, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\x01\x00' * int(16000 * seconds))
    return result.getvalue()


def test_reference_private_opaque_hashed_and_profile_compare_and_swap(tmp_path):
    store = profiles.VoiceProfileStore(tmp_path)
    default, digest = store.profile()
    assert default == profiles.DEFAULT_PROFILE and store.uses_default_voice()
    item = store.add_reference(pcm(), '合成测试', '这是合成测试。')
    assert len(item['id']) == 32 and '/' not in item['id']
    candidate = {**default, 'reference_id': item['id'], 'transcript': item['transcript'], 'style': '温柔自然'}
    saved, changed = store.save(candidate, digest)
    assert saved == candidate and changed != digest and not store.uses_default_voice()
    with pytest.raises(ValueError, match='voice_profile_changed'):
        store.save(default, digest)
    assert store.profile()[0] == candidate
    assert store.snapshot()['activation'] == 'next_synthesis'
    assert store.model_context()[1] == tmp_path / 'data/audio/voice-references' / (item['id'] + '.wav')
    audio_path = store.model_context()[1]
    audio_path.write_bytes(pcm(4))
    with pytest.raises(ValueError, match='voice_reference_changed'):
        store.profile()
    assert not store.uses_default_voice()


@pytest.mark.parametrize('data', [b'not wave', pcm(1), pcm(31), pcm()[:-2], pcm() + b'garbage', b'x' * (profiles.MAX_AUDIO_BYTES + 1)], ids=['not-wave', 'short', 'long', 'truncated', 'trailing', 'too-large'])
def test_bad_wave_rejected_before_creating_assets(tmp_path, data):
    store = profiles.VoiceProfileStore(tmp_path)
    with pytest.raises(ValueError):
        store.add_reference(data, '测试', '测试文本')
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('reference_id', ['../x', 'C:/secret.wav', 'https://example.invalid/a.wav', 123, ['x']], ids=['parent', 'drive', 'url', 'number', 'list'])
def test_no_arbitrary_reference_paths(tmp_path, reference_id):
    with pytest.raises(ValueError):
        profiles.VoiceProfileStore(tmp_path).validate_profile({**profiles.DEFAULT_PROFILE, 'reference_id': reference_id, 'transcript': '合成'})


def test_bad_text_and_foreign_symlink_do_not_write(tmp_path):
    store = profiles.VoiceProfileStore(tmp_path)
    for style in ('x' * 201, '<|endofprompt|>', 'line\nnext'):
        with pytest.raises(ValueError):
            store.validate_profile({**profiles.DEFAULT_PROFILE, 'style': style})
    (tmp_path / 'data/audio').mkdir(parents=True)
    external = tmp_path.parent / (tmp_path.name + '-outside')
    external.mkdir()
    link = tmp_path / 'data/audio/voice-references'
    try:
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                pytest.skip('symlink_permission_unavailable')
            result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(external)], capture_output=True)
            if result.returncode:
                pytest.skip('junction_permission_unavailable')
        with pytest.raises(ValueError, match='voice_path_rejected'):
            store.add_reference(pcm(), '合成', '文本')
        assert list(external.iterdir()) == []
    finally:
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            link.rmdir()  # 只移除本测试的联接入口，不递归处理目标。


def test_speaker_cache_keys_include_style_and_reference_and_stream_snapshot(tmp_path):
    from test_cosyvoice_service import service
    store = profiles.VoiceProfileStore(tmp_path)
    item = store.add_reference(pcm(), '合成', '这是测试。')
    calls = []
    class Model:
        model = SimpleNamespace(token_hop_len=100)
        frontend = SimpleNamespace(spk2info={})
        def add_zero_shot_spk(self, prompt, path, speaker):
            calls.append(('register', prompt, speaker)); self.frontend.spk2info[speaker] = {}; return True
        def inference_zero_shot(self, text, prompt, path, **kwargs):
            calls.append(('zero', prompt, kwargs['zero_shot_spk_id'])); yield {'tts_speech': object()}
        def inference_instruct2(self, text, prompt, path, **kwargs):
            calls.append(('instruct', prompt, kwargs['zero_shot_spk_id'])); yield {'tts_speech': object()}
    synth = object.__new__(service.CosyVoiceSynthesizer)
    synth._model = Model(); synth._profiles = store; synth._speaker_cache = service.OrderedDict()
    synth._lock = threading.Lock(); synth._stream_cache = service.OrderedDict(); synth._cache_entries = 8
    synth._prompt_wav = Path('official.wav'); synth.model_streaming = False; synth.stream_token_hop_len = 25
    synth._wave_bytes = lambda _speech: b'RIFF-test'
    default, digest = store.profile()
    custom = {**default, 'reference_id': item['id'], 'transcript': item['transcript']}
    _, digest = store.save(custom, digest)
    assert list(synth.stream_chunks('测试')) == [b'RIFF-test']
    assert list(synth.stream_chunks('测试')) == [b'RIFF-test']
    assert len(calls) == 2  # 第二次真正复用缓存。
    styled = {**custom, 'style': '温柔自然'}
    store.save(styled, digest)
    assert list(synth.stream_chunks('测试')) == [b'RIFF-test']
    assert calls[-1][0] == 'instruct' and '温柔自然<|endofprompt|>' in calls[-1][1]
    assert calls[-1][2] != calls[1][2]
    # 草稿试听不保存共享档案，并使用独立的 speaker/cache 键。
    assert list(synth.stream_chunks('测试', voice_profile={**styled, 'style': '平静'})) == [b'RIFF-test']
    assert store.profile()[0] == styled
    synth._cache = service.OrderedDict()
    synth._generate = lambda text, context: context['speaker'].encode()
    first = synth.synthesize('缓冲合成')
    assert synth.synthesize('缓冲合成') == first
    _, digest = store.profile()
    store.save({**styled, 'style': '开心'}, digest)
    assert synth.synthesize('缓冲合成') != first
