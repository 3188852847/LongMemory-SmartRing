from pathlib import Path
import importlib.util
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/cosyvoice/trial.py"
SPEC = importlib.util.spec_from_file_location("cosyvoice_trial_test", SCRIPT)
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


def make_files(root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        path = root / name
        if Path(name).suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        else:
            path.mkdir(parents=True, exist_ok=True)


def test_validate_local_files_accepts_complete_local_snapshot(tmp_path):
    source = tmp_path / "source"
    model = tmp_path / "model"
    make_files(source, trial.REQUIRED_SOURCE)
    make_files(model, trial.REQUIRED_MODEL)

    result = trial.validate_local_files(source, model)

    assert result["source_root"] == str(source.resolve())
    assert result["model_dir"] == str(model.resolve())
    assert result["prompt_wav"].endswith("zero_shot_prompt.wav")


def test_validate_local_files_does_not_require_optional_speaker_catalog(tmp_path):
    source = tmp_path / "source"
    model = tmp_path / "model"
    make_files(source, trial.REQUIRED_SOURCE)
    make_files(model, trial.REQUIRED_MODEL)

    assert not (model / "spk2info.pt").exists()
    trial.validate_local_files(source, model)


def test_validate_local_files_reports_missing_model_without_importing_engine(tmp_path):
    source = tmp_path / "source"
    model = tmp_path / "model"
    make_files(source, trial.REQUIRED_SOURCE)
    model.mkdir()

    with pytest.raises(ValueError, match="cosyvoice3.yaml"):
        trial.validate_local_files(source, model)


@pytest.fixture
def modelscope_runtime(monkeypatch, tmp_path):
    """用会立即失败的下载入口模拟上游，测试不得联网或改写第三方缓存。"""
    cache = tmp_path / "existing-cache"
    repo = cache / trial.WETEXT_MODEL_ID
    make_files(repo, trial.WETEXT_REQUIRED_FILES)
    metadata = repo / ".mdl"
    metadata.write_bytes(b"existing model metadata")

    def snapshot(repo_id, *, repo_type=None, revision="master", cache_dir=None,
                 local_files_only=False, local_dir=None):
        raise AssertionError("不得调用会创建缓存、查询元数据或下载的原入口")

    def file_download(repo_id, file_path, *, repo_type=None, revision="master",
                      cache_dir=None, local_files_only=False, local_dir=None):
        raise AssertionError("不得调用会创建缓存、查询元数据或下载的原入口")

    snapshot_module = SimpleNamespace(_snapshot_download=snapshot)
    file_module = SimpleNamespace(_repo_file_download=file_download)
    version = SimpleNamespace(__version__="1.20.0")
    modules = {
        "modelscope.version": version,
        "modelscope.hub.snapshot_download": snapshot_module,
        "modelscope.hub.file_download": file_module,
        "modelscope.utils.file_utils": SimpleNamespace(get_model_cache_root=lambda: cache),
    }
    monkeypatch.setattr(trial, "import_module", modules.__getitem__)

    def public_snapshot(model_id, revision="master", cache_dir=None, user_agent=None,
                        local_files_only=False, local_dir=None):
        return snapshot_module._snapshot_download(
            model_id, repo_type="model", revision=revision, cache_dir=cache_dir,
            local_files_only=local_files_only, local_dir=local_dir,
        )

    return SimpleNamespace(
        cache=cache, repo=repo, metadata=metadata, version=version,
        snapshot_module=snapshot_module, file_module=file_module,
        imported_snapshot=public_snapshot,
    )


def test_offline_resolves_existing_cache_through_preimported_alias(modelscope_runtime):
    state = modelscope_runtime
    alias = state.imported_snapshot
    trial.install_modelscope_offline()

    # 故意以位置参数指定 False：公共函数原有默认值不能重新开启网络。
    assert alias(trial.WETEXT_MODEL_ID, "master", None, None, False) == str(state.repo)
    assert state.metadata.read_bytes() == b"existing model metadata"
    assert sorted(p.name for p in state.cache.iterdir()) == ["pengzhendong"]


@pytest.mark.parametrize("local_dir", [False, True])
def test_offline_preserves_explicit_cache_locations(modelscope_runtime, tmp_path, local_dir):
    state = modelscope_runtime
    custom = tmp_path / "explicit"
    expected = custom if local_dir else custom / trial.WETEXT_MODEL_ID
    make_files(expected, trial.WETEXT_REQUIRED_FILES)
    trial.install_modelscope_offline()

    kwargs = {"local_dir": custom, "cache_dir": tmp_path / "ignored"} if local_dir else {"cache_dir": custom}
    assert state.imported_snapshot(trial.WETEXT_MODEL_ID, **kwargs) == str(expected)
    assert not (tmp_path / "ignored").exists()


def test_offline_missing_cache_fails_without_creating_files(modelscope_runtime, tmp_path):
    trial.install_modelscope_offline()
    missing = tmp_path / "missing-cache"

    with pytest.raises(FileNotFoundError, match="禁止自动下载"):
        modelscope_runtime.imported_snapshot(trial.WETEXT_MODEL_ID, cache_dir=missing)
    assert not missing.exists()


def test_offline_incomplete_wetext_cache_is_not_reported_ready(modelscope_runtime, tmp_path):
    partial = tmp_path / "partial"
    make_files(partial / trial.WETEXT_MODEL_ID, trial.WETEXT_REQUIRED_FILES[:-1])
    trial.install_modelscope_offline()

    with pytest.raises(FileNotFoundError, match="不完整"):
        modelscope_runtime.imported_snapshot(trial.WETEXT_MODEL_ID, cache_dir=partial)


def test_offline_file_entry_only_returns_verified_existing_fst(modelscope_runtime):
    state = modelscope_runtime
    trial.install_modelscope_offline()
    download = state.file_module._repo_file_download
    name = trial.WETEXT_REQUIRED_FILES[0]

    assert download(trial.WETEXT_MODEL_ID, name, local_files_only=False) == str(state.repo / name)
    with pytest.raises(FileNotFoundError, match="未验证"):
        download(trial.WETEXT_MODEL_ID, "../../unrelated.txt")


@pytest.mark.parametrize("repo_id,repo_type", [("unknown/model", "model"), (trial.WETEXT_MODEL_ID, "dataset")])
def test_offline_rejects_other_resources(modelscope_runtime, repo_id, repo_type):
    trial.install_modelscope_offline()
    with pytest.raises(ValueError):
        modelscope_runtime.snapshot_module._snapshot_download(repo_id, repo_type=repo_type)


def test_offline_unknown_version_does_not_call_download(modelscope_runtime):
    modelscope_runtime.version.__version__ = "9.9.9"
    trial.install_modelscope_offline()
    with pytest.raises(RuntimeError, match="未经验证"):
        modelscope_runtime.imported_snapshot(trial.WETEXT_MODEL_ID)


def test_offline_repeated_install_does_not_stack_wrappers(modelscope_runtime):
    trial.install_modelscope_offline()
    first = modelscope_runtime.snapshot_module._snapshot_download
    trial.install_modelscope_offline()
    assert modelscope_runtime.snapshot_module._snapshot_download is first


def test_offline_incompatible_download_entry_stops_startup(modelscope_runtime):
    modelscope_runtime.snapshot_module._snapshot_download = None
    with pytest.raises(RuntimeError, match="停止启动"):
        trial.install_modelscope_offline()


def test_runtime_cache_uses_project_root_without_moving_existing_cache(
    modelscope_runtime, monkeypatch, tmp_path,
):
    monkeypatch.setattr(trial, "ROOT", tmp_path)
    for key in ("NUMBA_CACHE_DIR", "MPLCONFIGDIR", "HF_HOME", "HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MODELSCOPE_CACHE", str(modelscope_runtime.cache))

    trial.configure_runtime_cache()

    # 新电脑使用项目专属 WeText 根；只改变本进程选择，不迁移或覆盖旧缓存。
    assert trial.os.environ["MODELSCOPE_CACHE"] == str(tmp_path / "local/runtime/modelscope-cache")
    assert all((modelscope_runtime.repo / name).is_file() for name in trial.WETEXT_REQUIRED_FILES)
    assert trial.os.environ["HF_HUB_OFFLINE"] == "1"
    assert modelscope_runtime.imported_snapshot(trial.WETEXT_MODEL_ID) == str(modelscope_runtime.repo)
