"""复用与独立语音Python相同的标准库摘要契约，不导入音频或模型。"""

from functools import lru_cache
import importlib.util
from pathlib import Path


@lru_cache(maxsize=1)
def contract_module():
    path = Path(__file__).resolve().parents[4] / 'scripts/development/xiaozhi/cosy_delivery_contract.py'
    spec = importlib.util.spec_from_file_location('longmemory_cosy_delivery_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cosy_delivery(value):
    try:
        return contract_module().project_observation(value)
    except Exception:
        return None
