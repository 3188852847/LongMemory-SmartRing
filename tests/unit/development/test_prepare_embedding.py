import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

from longmemory.adapters.llm.local_embedding import MODEL_FILES, REVISION


@pytest.fixture
def setup_module(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/development/prepare_embedding.py"
    spec = importlib.util.spec_from_file_location("prepare_embedding_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    files = {name: ("synthetic " + name).encode() for name in (*MODEL_FILES, "README.md")}
    metadata = {"sha": REVISION, "siblings": [
        {"rfilename": name, "blobId": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}
        for name, data in files.items()]}
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if "/api/models/" in url:
            return io.BytesIO(json.dumps(metadata).encode())
        return io.BytesIO(files[url.rsplit("/", 1)[1]])
    monkeypatch.setattr(module.urllib.request, "urlopen", get)
    return module, files, calls


def test_download_receipt_and_refuse_overwrite(setup_module):
    module, files, calls = setup_module
    module.main([])
    target = module.ROOT / "data/models/bge-small-zh-v1.5" / REVISION
    receipt = json.loads((target / "snapshot.json").read_text())
    assert receipt["files"] == {name: hashlib.sha256(files[name]).hexdigest() for name in MODEL_FILES}
    assert len(calls) == len(files) + 1
    with pytest.raises(ValueError):
        module.main([])
    assert len(calls) == len(files) + 1


def test_manual_import_missing_files_and_verify_existing(setup_module):
    module, files, calls = setup_module
    target = module.ROOT / "data/models/bge-small-zh-v1.5" / REVISION
    target.mkdir(parents=True)
    (target / "model.safetensors").write_bytes(files["model.safetensors"])
    manual = module.ROOT / "manual"
    manual.mkdir()
    for name, data in files.items():
        if name != "model.safetensors":
            (manual / name).write_bytes(data)
    module.main(["--from-directory", str(manual)])
    assert len(calls) == 1 and "/api/models/" in calls[0]
    assert (target / "snapshot.json").exists()


def test_existing_corruption_not_replaced(setup_module):
    module, files, calls = setup_module
    target = module.ROOT / "data/models/bge-small-zh-v1.5" / REVISION
    target.mkdir(parents=True)
    (target / "config.json").write_bytes(b"bad")
    with pytest.raises(ValueError):
        module.main([])
    assert (target / "config.json").read_bytes() == b"bad"
    assert not (target / "snapshot.json").exists()
