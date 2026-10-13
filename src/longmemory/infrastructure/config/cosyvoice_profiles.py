"""将独立 Python 3.10 的标准库档案契约接入网页服务，不导入语音模型。"""
from functools import lru_cache
import importlib.util
from pathlib import Path


@lru_cache(maxsize=1)
def profile_module():
    path = Path(__file__).resolve().parents[4] / 'scripts/development/cosyvoice/voice_profiles.py'
    spec = importlib.util.spec_from_file_location('longmemory_cosyvoice_profiles', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
