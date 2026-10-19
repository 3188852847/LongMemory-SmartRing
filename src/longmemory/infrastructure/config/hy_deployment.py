"""正式启动的可信 Hy 资源选择；HTTP 只允许选择后端枚举。

部署描述与模型设置只从项目固定私有位置读取。首次建库是切换所有者的
显式操作，普通启动仅重开，绝不把不存在的路径当作空库自动重建。
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path


@dataclass(frozen=True)
class HyDeployment:
    settings: object
    python: Path
    state_directory: Path
    source_path: Path
    python_version: str


def _read(path):
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("hy_deployment_file_missing_or_large")
    return json.loads(path.read_text(encoding="utf-8"))


def _path(root, value, *, parent):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("hy_deployment_relative_path_required")
    raw = root / value
    resolved = raw.resolve()
    if not resolved.is_relative_to(root / parent):
        raise ValueError("hy_deployment_path_outside_owner")
    for path in (raw, *raw.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError("hy_deployment_links_not_allowed")
        if path == root:
            break
    return resolved


def load_hy_deployment(root):
    from longmemory.methods.hy_memory.settings import HySettings
    root = Path(root).resolve()
    directory = root / "local/config/hy-memory"
    for path in (directory, directory.parent, directory / "deployment.json", directory / "settings.json"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("hy_deployment_links_not_allowed")
    data = _read(directory / "deployment.json")
    if not isinstance(data, dict) or set(data) != {"version", "python", "python_version", "python_sha256", "state_directory", "source_path", "settings_identity"} or data["version"] != 1:
        raise ValueError("hy_deployment_shape_invalid")
    if data["python_version"] != "3.12.13":
        raise ValueError("hy_deployment_python_version_unverified")
    python = _path(root, data["python"], parent="local")
    if not python.is_file() or python.name.lower() != "python.exe" or sha256(python.read_bytes()).hexdigest() != data["python_sha256"]:
        raise ValueError("hy_deployment_interpreter_mismatch")
    state = _path(root, data["state_directory"], parent="data/memory")
    sources = _path(root, data["source_path"], parent="data/databases")
    if state == sources or sources.is_relative_to(state) or state.is_relative_to(sources):
        raise ValueError("hy_deployment_resources_overlap")
    settings = HySettings.from_wire(_read(directory / "settings.json"))
    if settings.identity() != data["settings_identity"]:
        raise ValueError("hy_deployment_model_identity_mismatch")
    return HyDeployment(settings, python, state, sources, data["python_version"])


def build_daily_hy_runtime(root, *, create=False):
    from longmemory.bootstrap import build_hy_memory_runtime
    deployment = load_hy_deployment(root)
    if not deployment.settings.network_authorized or deployment.settings.model_mode == "synthetic_transport":
        raise ValueError("hy_daily_real_model_configuration_required")
    return build_hy_memory_runtime(settings=deployment.settings, python=deployment.python,
        state_directory=deployment.state_directory, source_path=deployment.source_path, create=create,
        expected_python_version=deployment.python_version)
