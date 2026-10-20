"""只读共享声线指针；自定义声线不混用官方预生成音频。"""
from functools import lru_cache
import importlib.util
from pathlib import Path
import hashlib
import json
import threading

ROOT = Path(__file__).resolve().parents[3]
WAITING_ENGINE = 'cosyvoice3/Fun-CosyVoice3-0.5B-2512/opus60-v1'
_waiting_lock = threading.Lock()
_waiting_cached = None


@lru_cache(maxsize=1)
def profile_store():
    spec = importlib.util.spec_from_file_location('xiaozhi_cosyvoice_profiles', ROOT / 'scripts/development/cosyvoice/voice_profiles.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.VoiceProfileStore(ROOT)


def default_voice_active():
    return profile_store().uses_default_voice()


def _stamp(path):
    if path is None:
        return None
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError('waiting_profile_path_invalid')
    try:
        value = path.stat()
        return value.st_size, value.st_mtime_ns, value.st_ctime_ns
    except FileNotFoundError:
        return None


def waiting_identity(digest):
    return hashlib.sha256((WAITING_ENGINE + ':' + digest).encode()).hexdigest()


def waiting_context():
    """仅返回声线摘要；文件未变时不反复读/校验私人参考 WAV。"""
    global _waiting_cached
    try:
        store = profile_store()
        with _waiting_lock:
            stamp = (str(store.root), _stamp(store.profile_path))
            old = _waiting_cached
            if (old and old['stamp'] == stamp
                    and all(_stamp(path) == saved for path, saved in old['references'])):
                return dict(old['context'])
            selected, reference, digest = store.model_context()
            if stamp != (str(store.root), _stamp(store.profile_path)):
                return None
            paths = [] if reference is None else [reference, reference.with_suffix('.json')]
            context = {'identity': waiting_identity(digest),
                'default': selected['reference_id'] is None and not selected['style']}
            _waiting_cached = {'stamp': stamp, 'references': [(p, _stamp(p)) for p in paths],
                'context': context}
            return dict(context)
    except (OSError, ValueError, TypeError, KeyError):
        return None  # 无法核验时不回退为原声线，也不合成临时提示。
