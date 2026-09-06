"""防止渐进式架构校准在后续功能中悄悄倒退。"""

import ast
import inspect
from pathlib import Path

from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.core.memory import models as legacy_models
from longmemory.core.memory.l1_atomic import models as l1_models


SRC = Path(__file__).parents[3] / "src" / "longmemory"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )


def test_legacy_l1_models_are_the_same_types_as_canonical_models():
    """兼容层必须转发类型身份，不能形成两套相似领域对象。"""

    for name in (
        "AtomicMemory",
        "MemoryEvidence",
        "MemoryOperationType",
        "MemorySourceType",
        "MemoryWriteOperation",
    ):
        assert getattr(legacy_models, name) is getattr(l1_models, name)


def test_memory_runtime_requires_an_injected_method():
    """应用运行时不能自行选择 LongMemoryV1 等具体策略。"""

    parameter = inspect.signature(MemoryRuntime).parameters["method"]
    assert parameter.default is inspect.Parameter.empty
    imports = _imports(SRC / "application" / "memory_runtime.py")
    assert not any(module.startswith("longmemory.methods.longmemory_v1") for module in imports)
    assert not any(module.startswith("longmemory.methods.daily_llm") for module in imports)


def test_application_layer_does_not_import_concrete_memory_methods():
    """具体方法只能由 bootstrap/入口装配，不能反向进入应用层。"""

    violations = []
    for path in (SRC / "application").rglob("*.py"):
        for module in _imports(path):
            if module.startswith("longmemory.methods.") and module != "longmemory.methods.contracts":
                violations.append(f"{path.relative_to(SRC)} -> {module}")
    assert violations == []


def test_production_code_uses_canonical_l1_model_path():
    """旧路径只为外部兼容保留，项目自身的新代码不得继续依赖它。"""

    allowed = {
        SRC / "core" / "memory" / "models.py",
    }
    violations = []
    for path in SRC.rglob("*.py"):
        if path in allowed:
            continue
        for module in _imports(path):
            if module == "longmemory.core.memory.models":
                violations.append(str(path.relative_to(SRC)))
    assert violations == []
