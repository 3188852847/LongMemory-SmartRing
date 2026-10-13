"""只读共享声线指针；自定义声线不混用官方预生成音频。"""
from functools import lru_cache
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def profile_store():
    spec = importlib.util.spec_from_file_location('xiaozhi_cosyvoice_profiles', ROOT / 'scripts/development/cosyvoice/voice_profiles.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.VoiceProfileStore(ROOT)


def default_voice_active():
    return profile_store().uses_default_voice()
