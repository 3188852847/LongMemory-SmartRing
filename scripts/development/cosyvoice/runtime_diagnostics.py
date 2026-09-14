"""CosyVoice 四个粗粒度阶段的内存累计计时，不保存文本或音频。

这些是方法调用的墙钟耗时，包含 Python 调度和方法内已有的等待；不做 CUDA
同步，因此不是纯 GPU 运行时间。LLM 线程与音频阶段可能重叠，不能直接相加。
只在每个阶段结束时更新一次计数，不在逐 token 路径增加观测开销。
"""

from __future__ import annotations

from functools import wraps
import inspect
import threading
from time import perf_counter


class RuntimeDiagnostics:
    """保护累计值与快照的一致性，锁不覆盖模型调用或生成线程。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._stages: dict[str, dict[str, int | float]] = {}

    def wrap(self, owner, method_name: str, stage: str) -> bool:
        original = getattr(owner, method_name, None)
        if not callable(original):
            return False
        # 当前四个方法都同步返回。若替身或未来版本改成生成器/协程，
        # 保留原方法，避免误把“创建生成器”统计成整个推理阶段。
        if inspect.isgeneratorfunction(original) or inspect.iscoroutinefunction(original):
            return False
        record: dict[str, int | float] = {"calls": 0, "wall_ms": 0.0}

        @wraps(original)
        def measured(*args, **kwargs):
            started = perf_counter()
            try:
                # original 已绑定原实例；调用线程、参数、返回对象及异常均照旧。
                return original(*args, **kwargs)
            finally:
                elapsed_ms = (perf_counter() - started) * 1000
                # 失败调用也计数，便于对照错误前后的实际占用；不记录异常内容。
                with self._lock:
                    record["calls"] += 1
                    record["wall_ms"] += elapsed_ms

        try:
            setattr(owner, method_name, measured)
        except (AttributeError, TypeError):
            return False
        with self._lock:
            self._stages[stage] = record
        return True

    def snapshot(self) -> dict[str, dict[str, int | float]]:
        """仅复制已结束调用的累计值；前后两份 health 的差值对应其间调用。"""
        with self._lock:
            return {
                stage: {"calls": record["calls"], "wall_ms": round(record["wall_ms"], 3)}
                for stage, record in self._stages.items()
            }


def install_runtime_diagnostics(cosyvoice) -> RuntimeDiagnostics:
    """只包装本服务实例的已知方法；缺少方法的测试替身自然跳过。"""
    diagnostics = RuntimeDiagnostics()
    runtime = getattr(cosyvoice, "model", None)
    for owner, method, stage in (
        (runtime, "llm_job", "llm_job"),
        (getattr(runtime, "flow", None), "inference", "flow"),
        (getattr(runtime, "hift", None), "inference", "hift"),
        (getattr(cosyvoice, "frontend", None), "text_normalize", "text_normalize"),
    ):
        diagnostics.wrap(owner, method, stage)
    return diagnostics
