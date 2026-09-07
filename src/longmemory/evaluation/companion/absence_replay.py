"""用固定合成时间线回放缺席策略草案和既有 P4 安全门控。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

from longmemory.core.companion import (
    AbsenceRoutineDraft,
    AbsenceRoutineState,
    AbsenceTriggerAction,
    decide_routine_absence,
)
from longmemory.core.proactive import (
    OutreachPolicyAction,
    OutreachPolicyConfig,
    OutreachPolicyState,
    OutreachTrigger,
    ProactiveOutreach,
    decide_outreach,
)


DEFAULT_DATASET = (
    Path(__file__).resolve().parents[4]
    / "datasets" / "synthetic" / "companion_absence_replay_v1.json"
)


@dataclass(frozen=True, slots=True)
class ReplayCase:
    case_id: str
    now: datetime
    draft: AbsenceRoutineDraft
    absence_state: AbsenceRoutineState
    outreach_config: OutreachPolicyConfig
    outreach_state: OutreachPolicyState
    device_ready: bool
    must_not_contact: bool
    expected_action: str
    expected_reason: str


@dataclass(frozen=True, slots=True)
class ReplayDataset:
    name: str
    version: str
    sha256: str
    cases: tuple[ReplayCase, ...]


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field}_invalid")
    return value


def _time(value: Any, field: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}_timezone_required")
    return parsed


def _bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field}_invalid")
    return value


def _integer(value: Any, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field}_invalid")
    return value


def load_replay_dataset(path: Path = DEFAULT_DATASET) -> ReplayDataset:
    raw = path.read_bytes()
    if len(raw) > 500_000:
        raise ValueError("companion_replay_dataset_too_large")
    data = json.loads(raw)
    if data.get("schema_version") != 1 or data.get("synthetic") is not True:
        raise ValueError("companion_replay_dataset_contract_invalid")

    rows = data.get("cases")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("companion_replay_case_count_invalid")
    cases: list[ReplayCase] = []
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("companion_replay_case_invalid")
        case_id = _text(row.get("id"), "case_id")
        if case_id in ids:
            raise ValueError("companion_replay_case_id_duplicate")
        ids.add(case_id)
        now = _time(row.get("now"), "case_now")
        draft_data = row.get("draft", {})
        absence_data = row.get("absence_state", {})
        outreach_data = row.get("outreach", {})
        attempted = tuple(
            _time(value, "attempted_at") for value in outreach_data.get("attempted_at", [])
        )
        quiet_raw = outreach_data.get("quiet_until")
        expected = row.get("expected", {})
        cases.append(ReplayCase(
            case_id=case_id,
            now=now,
            draft=AbsenceRoutineDraft(
                candidate_id=_text(draft_data.get("candidate_id", "routine-demo"), "candidate_id"),
                expected_minute=_integer(draft_data.get("expected_minute", 13 * 60), "expected_minute"),
                grace_minutes=_integer(draft_data.get("grace_minutes", 60), "grace_minutes"),
                utc_offset_minutes=_integer(draft_data.get("utc_offset_minutes", 8 * 60), "utc_offset_minutes"),
                allowed_weekdays=tuple(draft_data.get("allowed_weekdays", range(7))),
                enabled=_bool(draft_data.get("enabled", True), "draft_enabled"),
            ),
            absence_state=AbsenceRoutineState(
                routine_observed_today=_bool(absence_data.get("routine_observed_today", False), "routine_observed_today"),
                user_chatted_today=_bool(absence_data.get("user_chatted_today", False), "user_chatted_today"),
                already_evaluated_today=_bool(absence_data.get("already_evaluated_today", False), "already_evaluated_today"),
            ),
            outreach_config=OutreachPolicyConfig(
                enabled=_bool(outreach_data.get("enabled", True), "outreach_enabled"),
                utc_offset_minutes=_integer(draft_data.get("utc_offset_minutes", 8 * 60), "utc_offset_minutes"),
                allowed_weekdays=tuple(outreach_data.get("allowed_weekdays", range(7))),
                allowed_start_minute=_integer(outreach_data.get("allowed_start_minute", 9 * 60), "allowed_start_minute"),
                allowed_end_minute=_integer(outreach_data.get("allowed_end_minute", 21 * 60), "allowed_end_minute"),
                daily_limit=_integer(outreach_data.get("daily_limit", 1), "daily_limit"),
                minimum_interval=timedelta(minutes=_integer(outreach_data.get("minimum_interval_minutes", 360), "minimum_interval_minutes")),
                maximum_lifetime=timedelta(minutes=5),
            ),
            outreach_state=OutreachPolicyState(
                attempted_at=attempted,
                awaiting_user_response=_bool(outreach_data.get("awaiting_user_response", False), "awaiting_user_response"),
                user_session_active=_bool(outreach_data.get("user_session_active", False), "user_session_active"),
                quiet_until=_time(quiet_raw, "quiet_until") if quiet_raw is not None else None,
            ),
            device_ready=_bool(row.get("device_ready", True), "device_ready"),
            must_not_contact=_bool(row.get("must_not_contact", False), "must_not_contact"),
            expected_action=_text(expected.get("action"), "expected_action"),
            expected_reason=_text(expected.get("reason"), "expected_reason"),
        ))
    return ReplayDataset(
        _text(data.get("name"), "dataset_name"),
        _text(data.get("version"), "dataset_version"),
        hashlib.sha256(raw).hexdigest(),
        tuple(cases),
    )


def replay_case(case: ReplayCase) -> tuple[str, str]:
    """返回最终可比较结果；这里只报告“会排队”，绝不真的投递。"""

    absence = decide_routine_absence(case.draft, now=case.now, state=case.absence_state)
    if absence.action == AbsenceTriggerAction.WAIT:
        return "wait", absence.reason.value
    if absence.action == AbsenceTriggerAction.SKIP:
        return "skipped", absence.reason.value

    assert absence.check_at is not None and absence.idempotency_key is not None
    outreach = ProactiveOutreach(
        id=f"replay-{case.case_id}",
        subject_id="user:self",
        trigger=OutreachTrigger.HABIT_CANDIDATE,
        trigger_reason_code=absence.reason.value,
        content="合成回放问候",
        created_at=absence.check_at,
        scheduled_for=absence.check_at,
        expires_at=absence.check_at + timedelta(minutes=5),
        idempotency_key=absence.idempotency_key,
    )
    policy = decide_outreach(
        outreach,
        now=case.now,
        state=case.outreach_state,
        config=case.outreach_config,
    )
    if policy.action != OutreachPolicyAction.ALLOW:
        return ("wait" if policy.action == OutreachPolicyAction.WAIT else "blocked"), policy.reason.value
    if not case.device_ready:
        return "blocked", "device_not_ready"
    return "would_queue", "ready"


def run_replay(dataset: ReplayDataset) -> dict[str, Any]:
    results = []
    unsafe_allows = 0
    for case in dataset.cases:
        action, reason = replay_case(case)
        matched = action == case.expected_action and reason == case.expected_reason
        unsafe = case.must_not_contact and action == "would_queue"
        unsafe_allows += int(unsafe)
        results.append({
            "case_id": case.case_id,
            "action": action,
            "reason": reason,
            "expected_action": case.expected_action,
            "expected_reason": case.expected_reason,
            "matched": matched,
            "unsafe_allow": unsafe,
        })
    passed = sum(item["matched"] for item in results)
    gate_passed = passed == len(results) and unsafe_allows == 0
    return {
        "protocol": "companion-absence-offline-replay-v1",
        "dataset": {
            "name": dataset.name,
            "version": dataset.version,
            "sha256": dataset.sha256,
            "synthetic": True,
        },
        "summary": {
            "total": len(results),
            "matched": passed,
            "unsafe_allow_count": unsafe_allows,
            "gate_passed": gate_passed,
        },
        "results": results,
        "limitations": [
            "固定合成回放只验证工程规则，不证明真实用户会喜欢主动联系。",
            "通过门控不等于策略已激活，也不会向设备发送消息。",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线回放习惯缺席策略草案，不连接设备。")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_replay(load_replay_dataset(args.dataset))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"报告：{args.output.resolve()}")
    summary = report["summary"]
    print(
        f"离线回放：{summary['matched']}/{summary['total']} 个预期匹配；"
        f"不安全放行 {summary['unsafe_allow_count']}；"
        f"门控{'通过' if summary['gate_passed'] else '未通过'}。"
    )
    print("只验证固定合成规则；未连接模型、数据库或圆屏，也未激活策略。")
    return 0 if summary["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
