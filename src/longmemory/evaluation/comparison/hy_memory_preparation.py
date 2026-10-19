"""复用 comparison 数据类型，准备开发集；不装配/运行 Hy 或读取保留题。"""

import argparse
import json
from pathlib import Path

from .dataset import Dataset, load_dataset


def history_payload(dataset: Dataset) -> list[dict]:
    # 明确白名单，评分标签永不进入写入侧。
    return [{"event_id": event.event_id, "role": event.role, "content": event.content,
             "occurred_at": event.occurred_at.isoformat(), "session_id": event.session_id}
            for event in dataset.history]


def prepare_development(path: Path) -> dict:
    dataset = load_dataset(path)
    if any(question.split != "dev" for question in dataset.questions):
        raise ValueError("准备命令仅接受独立开发集，保留集不用于适配调试。")
    return {"stage": "preparation_only", "dataset": {"name": dataset.name,
            "version": dataset.version, "sha256": dataset.sha256},
            "history_count": len(history_payload(dataset)),
            "question_ids": [question.id for question in dataset.questions],
            "categories": sorted({question.category for question in dataset.questions}),
            "sdk_run": False, "answer_run": False,
            "assembly_implemented": True, "runtime_environment_checked": False,
            "pending": ["verify_owner_installed_environment", "explicit_model_endpoints_and_budget",
                        "real_model_semantic_state_audit", "real_qa_quality"]}


def changed_files(before: dict[str, str], after: dict[str, str]) -> dict:
    """字节变化不自动归因；不以文件名把语义变更豁免为遥测。"""
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    return {"byte_state_unchanged": not changed, "changed_files": changed,
            "semantic_state_unchanged": None,
            "classification": "no_byte_change" if not changed else "requires_store_level_review"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare_development(args.dataset), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
