"""离线回放必须精确匹配，并把任何不安全放行作为门控失败。"""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from longmemory.evaluation.companion.absence_replay import (
    DEFAULT_DATASET,
    load_replay_dataset,
    run_replay,
)


def test_fixed_synthetic_replay_passes_all_gates():
    report = run_replay(load_replay_dataset())
    assert report["summary"] == {
        "total": 16,
        "matched": 16,
        "unsafe_allow_count": 0,
        "gate_passed": True,
    }


def test_unexpected_allow_is_both_mismatch_and_safety_failure():
    dataset = load_replay_dataset()
    positive = next(case for case in dataset.cases if case.case_id == "absence-ready")
    unsafe = replace(positive, must_not_contact=True)
    report = run_replay(replace(dataset, cases=(unsafe,)))
    assert report["summary"]["unsafe_allow_count"] == 1
    assert report["summary"]["gate_passed"] is False


def test_duplicate_case_id_is_rejected():
    data = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    data["cases"].append(data["cases"][0])
    # 项目路径含中文时，某些 Windows Python/Tcl 环境会误解 pytest 的
    # basetemp；系统临时目录能让本测试只验证数据契约，而不是路径编码。
    with TemporaryDirectory(prefix="longmemory-replay-") as temp_dir:
        path = Path(temp_dir) / "duplicate.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match="case_id_duplicate"):
            load_replay_dataset(path)
