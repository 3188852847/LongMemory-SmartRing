"""纯标准库声音档案；Python 3.10 服务与 3.12 网页共用同一受控格式。

参考音频是私有用户资产，不是模型。只接受经过结构验证的 PCM WAV，不加载
上传对象，不接受文件系统路径或远程地址；音色选择在下一次合成开始时取快照。
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import wave

MAX_AUDIO_BYTES = 4 * 1024 * 1024
DEFAULT_PROFILE = {'version': 1, 'reference_id': None, 'transcript': '', 'style': ''}
PREVIEW_TEXT = '你好，这是声音试听。我们可以慢慢聊，我会认真听你说。'
_ID = re.compile(r'^[a-f0-9]{32}$')


def bounded_text(value, limit, *, required=False):
    if (not isinstance(value, str) or len(value) > limit
            or any(ord(char) < 32 for char in value) or '<|' in value or '|>' in value
            or (required and not value.strip())):
        raise ValueError('invalid_voice_text')
    return value.strip()


def validate_wav(data):
    """读取所有声明帧，拒绝压缩、截断、超长和空音频，保持原上传字节。"""
    if not isinstance(data, bytes) or not 44 <= len(data) <= MAX_AUDIO_BYTES:
        raise ValueError('invalid_reference_audio')
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE' or int.from_bytes(data[4:8], 'little') + 8 != len(data):
        raise ValueError('invalid_reference_audio')
    try:
        with wave.open(BytesIO(data), 'rb') as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if (audio.getcomptype() != 'NONE' or channels not in {1, 2} or width != 2
                    or not 16000 <= rate <= 48000 or not 3 <= frames / rate <= 30):
                raise ValueError('invalid_reference_audio')
            raw = audio.readframes(frames)
            if len(raw) != frames * channels * width or not any(raw):
                raise ValueError('invalid_reference_audio')
    except (wave.Error, EOFError, ZeroDivisionError) as error:
        raise ValueError('invalid_reference_audio') from error
    return {'duration_seconds': round(frames / rate, 3), 'sample_rate': rate, 'channels': channels,
            'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


class VoiceProfileStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.profile_path = self.root / 'local/config/voices/CosyVoice3.json'
        self.audio_root = self.root / 'data/audio/voice-references'

    def _contained(self, path):
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or path.is_symlink():
            raise ValueError('voice_path_rejected')
        return resolved

    def _read(self, path, limit):
        self._contained(path)
        if path.stat().st_size > limit:
            raise ValueError('voice_file_invalid')
        return path.read_bytes()

    @contextmanager
    def _writing(self):
        self._contained(self.profile_path.parent)
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.profile_path.with_suffix('.lock')
        self._contained(lock)
        # OS 持有锁的生命周期，进程崩溃也会释放；固定 lock 文件本身保留，
        # 避免 unlink 后另一个写者锁住旧 inode、第三个写者却新建文件的竞态。
        with lock.open('a+b') as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError('voice_profile_busy') from None
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _atomic(self, path, data):
        self._contained(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def references(self):
        self._contained(self.audio_root)
        result = []
        if self.audio_root.is_dir():
            for path in sorted(self.audio_root.glob('*.json')):
                try:
                    item = json.loads(self._read(path, 8192))
                    self.reference(item['id'])
                    result.append(item)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
        return result

    def reference(self, reference_id):
        if not isinstance(reference_id, str) or not _ID.fullmatch(reference_id):
            raise ValueError('invalid_voice_reference')
        metadata = json.loads(self._read(self.audio_root / (reference_id + '.json'), 8192))
        if (not isinstance(metadata, dict) or metadata.get('id') != reference_id
                or set(metadata) != {'id', 'label', 'transcript', 'duration_seconds', 'sample_rate', 'channels', 'sha256', 'bytes'}):
            raise ValueError('invalid_voice_reference')
        bounded_text(metadata.get('label'), 80, required=True)
        bounded_text(metadata.get('transcript'), 500, required=True)
        path = self.audio_root / (reference_id + '.wav')
        details = validate_wav(self._read(path, MAX_AUDIO_BYTES))
        if any(metadata.get(key) != value for key, value in details.items()):
            raise ValueError('voice_reference_changed')
        return metadata, path

    def add_reference(self, data, label, transcript):
        label = bounded_text(label, 80, required=True)
        transcript = bounded_text(transcript, 500, required=True)
        metadata = validate_wav(data)
        with self._writing():
            self._contained(self.audio_root)
            if self.audio_root.is_dir() and sum(1 for _ in self.audio_root.glob('*.json')) >= 32:
                raise ValueError('voice_reference_library_full')
            reference_id = secrets.token_hex(16)
            metadata.update(id=reference_id, label=label, transcript=transcript)
            self._atomic(self.audio_root / (reference_id + '.wav'), data)
            self._atomic(self.audio_root / (reference_id + '.json'), json.dumps(metadata, ensure_ascii=False).encode())
        return metadata

    def validate_profile(self, profile):
        if (not isinstance(profile, dict) or set(profile) != set(DEFAULT_PROFILE)
                or type(profile.get('version')) is not int or profile['version'] != 1):
            raise ValueError('invalid_voice_profile')
        result = dict(profile)
        result['style'] = bounded_text(profile['style'], 200)
        result['transcript'] = bounded_text(profile['transcript'], 500, required=profile['reference_id'] is not None)
        if profile['reference_id'] is not None:
            self.reference(profile['reference_id'])
        elif result['transcript']:
            raise ValueError('invalid_voice_profile')
        return result

    def profile(self):
        try:
            raw = self._read(self.profile_path, 8192)
        except FileNotFoundError:
            raw = b'<missing>'
            profile = dict(DEFAULT_PROFILE)
        else:
            profile = self.validate_profile(json.loads(raw))
        return profile, hashlib.sha256(raw).hexdigest()

    def save(self, profile, expected_digest):
        candidate = self.validate_profile(profile)
        with self._writing():
            _, digest = self.profile()
            if not isinstance(expected_digest, str) or digest != expected_digest:
                raise ValueError('voice_profile_changed')
            self._atomic(self.profile_path, json.dumps(candidate, ensure_ascii=False, indent=2).encode())
        return self.profile()

    def snapshot(self):
        profile, digest = self.profile()
        return {'profile': profile, 'profile_digest': digest, 'references': self.references(),
                'preview_text': PREVIEW_TEXT, 'activation': 'next_synthesis',
                'limits': {'max_audio_bytes': MAX_AUDIO_BYTES, 'min_seconds': 3, 'max_seconds': 30,
                           'format': 'PCM16 WAV', 'style_max_chars': 200}}

    def model_context(self, profile=None):
        selected = self.profile()[0] if profile is None else self.validate_profile(profile)
        reference = self.reference(selected['reference_id']) if selected['reference_id'] else None
        identity = {**selected, 'reference_sha256': reference[0]['sha256'] if reference else None}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return selected, reference[1] if reference else None, digest

    def uses_default_voice(self):
        try:
            profile, _ = self.profile()
            return profile['reference_id'] is None and not profile['style']
        except (OSError, ValueError):
            # 配置坏了也不能播放旧声线，正常合成由服务明确拒绝。
            return False
