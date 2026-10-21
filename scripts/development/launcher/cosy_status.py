"""声音模式的启动选择与显示边界；配置不冒充连接内实际策略。"""
from functools import lru_cache
import importlib.util
from pathlib import Path

@lru_cache(maxsize=1)
def contract_module():
    path = Path(__file__).resolve().parents[1] / 'xiaozhi/cosy_delivery_contract.py'
    spec = importlib.util.spec_from_file_location('launcher_cosy_delivery_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

MODES = contract_module().MODES
project_observation = contract_module().project_observation

def selection(*, voice, voice_mode, tts_backend, saved_mode, environment):
    if not (voice and voice_mode == "pipeline" and tts_backend == "cosyvoice3"):
        return None, None
    value = environment.get("LONGMEMORY_COSY_DELIVERY_MODE", saved_mode)
    if type(value) is not str or value not in MODES:
        raise ValueError("未知声音交付策略，请核对本次启动的覆盖值。")
    return value, "environment" if "LONGMEMORY_COSY_DELIVERY_MODE" in environment else "preference"


def launcher_summary(manager, settings, environment):
    """轮询只读已知启动事实；缺少AD连接证据时保持null。"""
    try:
        planned, source = selection(voice=settings['voice'], voice_mode=settings['voice_mode'],
            tts_backend=settings['tts_backend'], saved_mode=settings['cosy_delivery_mode'], environment=environment)
        valid = True
    except ValueError:
        planned, source, valid = None, 'environment', False
    running = bool(manager.services and 'voice' in manager.services)
    startup = getattr(manager, 'cosy_startup_mode', None) if running else None
    if type(startup) is not str or startup not in MODES:
        startup = None
    startup_source = getattr(manager, 'cosy_startup_source', None) if startup else None
    if startup_source not in ('environment', 'preference'):
        startup_source = None
    getter = getattr(manager, 'current_cosy_delivery', None)
    try:
        observation = project_observation(getter()) if running and callable(getter) else None
    except Exception:
        observation = None
    return dict(version=1, next_start_mode=planned, next_start_source=source,
                selection_valid=valid, startup_mode=startup, startup_source=startup_source,
                observation=observation, restart_required=bool(valid and startup and planned != startup or
                    observation is not None and observation['restart_required']))
