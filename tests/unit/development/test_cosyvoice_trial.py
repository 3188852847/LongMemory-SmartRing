from pathlib import Path
import importlib.util

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
