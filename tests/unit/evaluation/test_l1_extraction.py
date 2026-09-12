import json
from pathlib import Path

from longmemory.evaluation.l1_extraction import (
    _has_exact_assignment,
    load_l1_extraction_dataset,
    main,
    run_l1_extraction,
)


ROOT = Path(__file__).parents[3]
DATASET = ROOT / "datasets/synthetic/l1_extraction_v2.json"


class LabelOracleProducer:
    """测试评估器的离线替身；不代表真实提取质量。"""

    def __init__(self, cases):
        self._cases = {case["input"]: case for case in cases}
        self.calls = 0

    def propose(self, *, source_text: str) -> str:
        self.calls += 1
        case = self._cases.get(source_text)
        if case is None:
            case = next(case for full_text, case in self._cases.items()
                        if full_text.startswith(source_text))
        if case["expected_operation"] == "NOOP":
            return json.dumps({"schema_version": 1, "operation": "NOOP", "facts": []})
        facts = [
            {"content": "，".join(fact["required_terms"]), "quote": source_text}
            for fact in case["expected_facts"]
        ]
        return json.dumps({"schema_version": 1, "operation": "ADD", "facts": facts})


def test_dev_run_keeps_fixed_denominator_and_handles_trailing_reciprocal_question(tmp_path):
    dataset = load_l1_extraction_dataset(DATASET)
    producer = LabelOracleProducer(dataset.cases)

    directory, report = run_l1_extraction(
        dataset, producer, output_root=tmp_path,
        model_config={"provider": "synthetic-label-oracle"},
    )

    assert report["status"] == "completed"
    assert report["summary"] == {
        "total": 16,
        "completed": 16,
        "failed": 0,
        "request_attempts": producer.calls,
        "operation_exact": 16,
        "fact_count_exact": 16,
        "fact_match_exact": 16,
        "add_cases": 10,
        "add_exact": 10,
        "noop_cases": 6,
        "noop_exact": 6,
    }
    assert (directory / "manifest.json").is_file()
    assert (directory / "report.json").is_file()
    assert not (directory / "report.json.tmp").exists()


def test_failure_is_counted_without_dropping_case_from_denominator():
    dataset = load_l1_extraction_dataset(DATASET)

    class FailingProducer:
        def propose(self, *, source_text: str) -> str:
            raise RuntimeError("do not leak this")

    _directory, report = run_l1_extraction(dataset, FailingProducer())

    assert report["summary"]["total"] == 16
    assert report["summary"]["failed"] > 0
    assert report["summary"]["completed"] + report["summary"]["failed"] == 16
    assert {row["error"] for row in report["rows"] if row["status"] == "failed"} == {
        "candidate_extraction_failed"
    }


def test_one_candidate_cannot_satisfy_two_expected_facts():
    expected = [
        {"required_terms": ["用户", "喜欢"], "forbidden_terms": []},
        {"required_terms": ["用户", "乌龙茶"], "forbidden_terms": []},
    ]

    assert not _has_exact_assignment(("用户喜欢乌龙茶",), expected)


def test_cli_requires_explicit_model_and_holdout_permissions(capsys):
    assert main(["--model-profile", "official"]) == 2
    assert main([
        "--model-profile", "official", "--split", "holdout",
        "--allow-model-requests",
    ]) == 2
    assert "未显式允许" in capsys.readouterr().out
