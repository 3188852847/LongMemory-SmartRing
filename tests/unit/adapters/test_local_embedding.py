from contextlib import nullcontext
import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from longmemory.adapters.llm import local_embedding as local


def make_snapshot(tmp_path):
    for name in local.MODEL_FILES:
        (tmp_path / name).write_bytes(b"synthetic bytes, not model weights")
    receipt = {"model": local.MODEL_ID, "revision": local.REVISION, "files": local.snapshot_hashes(tmp_path)}
    (tmp_path / "snapshot.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_local_loading_never_allows_remote_code_or_implicit_download(tmp_path, monkeypatch):
    make_snapshot(tmp_path)
    auto_model, auto_tokenizer = MagicMock(), MagicMock()
    monkeypatch.setitem(sys.modules, "torch", MagicMock())
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=auto_model, AutoTokenizer=auto_tokenizer))
    monkeypatch.setattr(local, "version", lambda name: "test-version")
    encoder = local.LocalBGEEncoder(tmp_path)
    assert auto_model.from_pretrained.call_args.kwargs == {
        "local_files_only": True, "trust_remote_code": False, "use_safetensors": True}
    assert auto_tokenizer.from_pretrained.call_args.kwargs == {"local_files_only": True, "trust_remote_code": False}
    auto_model.from_pretrained.return_value.to.assert_called_once_with("cpu")
    assert encoder.metadata["query_prefix"] == local.QUERY_PREFIX
    assert encoder.identity == local.fingerprint(encoder.metadata)


@pytest.mark.parametrize("mutation", ["bytes", "revision", "missing"])
def test_bad_snapshot_rejected_before_model_loading(tmp_path, mutation):
    make_snapshot(tmp_path)
    if mutation == "bytes":
        (tmp_path / "config.json").write_bytes(b"changed")
    elif mutation == "revision":
        receipt = json.loads((tmp_path / "snapshot.json").read_text())
        receipt["revision"] = "main"
        (tmp_path / "snapshot.json").write_text(json.dumps(receipt))
    else:
        (tmp_path / "config.json").unlink()
    with pytest.raises(ValueError):
        local.LocalBGEEncoder(tmp_path)


def encoder_double(length):
    encoder = local.LocalBGEEncoder.__new__(local.LocalBGEEncoder)
    encoder._tokenizer = MagicMock(return_value={"input_ids": SimpleNamespace(shape=(1, length))})
    encoder._torch = MagicMock()
    encoder._torch.inference_mode.side_effect = nullcontext
    encoder._torch.nn.functional.normalize.return_value.cpu.return_value.tolist.return_value = [[1., 0.]]
    encoder._model = MagicMock()
    return encoder


def test_query_instruction_only_on_query_and_cls_pooling():
    encoder = encoder_double(20)
    assert encoder.encode_query("我是谁") == [1., 0.]
    assert encoder._tokenizer.call_args.args[0] == [local.QUERY_PREFIX + "我是谁"]
    assert encoder._tokenizer.call_args.kwargs["truncation"] is False
    encoder.encode_documents(["用户叫林澄"])
    assert encoder._tokenizer.call_args.args[0] == ["用户叫林澄"]
    args = encoder._model.return_value.last_hidden_state.__getitem__.call_args.args
    assert args == ((slice(None), 0),)
    assert encoder._torch.nn.functional.normalize.call_args.kwargs == {"p": 2, "dim": 1}


def test_overlength_and_empty_are_not_silently_embedded():
    encoder = encoder_double(513)
    with pytest.raises(ValueError):
        encoder.encode_query("超长合成句")
    encoder._model.assert_not_called()
    for text in ["", "   ", None]:
        with pytest.raises(ValueError):
            encoder.encode_query(text)
    assert encoder.encode_documents([]) == []
