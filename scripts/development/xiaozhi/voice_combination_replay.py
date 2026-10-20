"""合成事件组合审查；不安装业务钩子、不联网、不读取配置或加载模型。

输入不是生产诊断事件。它只验证未来适配器应满足的轮次/版本/音频边界，
不能据通过结果声称真实 SDK 无副作用、真实首声已播放或生产功能已接入。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
from statistics import median


SCHEMA = "synthetic-voice-combination-v1"
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "datasets/synthetic/hy-advanced-combination-v1.json"
MAX_BYTES = 1_000_000
EVENTS = frozenset({
    "turn_started", "user_end", "asr_final", "eou_confirmed", "resumed",
    "memory_snapshot", "memory_changed", "candidate_started", "candidate_ready", "candidate_cost",
    "candidate_adopted", "candidate_discarded", "cancelled", "llm_first_text",
    "tts_first_packet", "audio_sent", "playback_observed", "user_committed",
    "answer_committed", "tool_effect", "usage",
})
FIELDS = frozenset({
    "event", "at_ms", "clock_id", "turn", "transcript_revision", "memory_revision",
    "audio_epoch", "candidate", "kind", "actor", "evidence", "duration_ms",
    "prompt_tokens", "cache_hit_tokens", "cache_miss_tokens", "output_tokens",
})
IDENTITY = ("transcript_revision", "memory_revision", "audio_epoch")
STAGES = ("user_end", "asr_final", "eou_confirmed", "memory_snapshot",
          "llm_first_text", "tts_first_packet", "audio_sent", "playback_observed")


def _label(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is not None


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 3_600_000


def _counter(value):
    return type(value) is int and 0 <= value <= 1_000_000_000


@dataclass
class Candidate:
    identity: tuple
    state: str = "running"
    duration_ms: float | None = None
    output_tokens: int | None = None
    cost_recorded: bool = False


@dataclass
class Turn:
    identity: tuple
    cancelled: bool = False
    snapshot: tuple | None = None
    final: bool = False
    confirmed: bool = False
    stages: dict = field(default_factory=dict)
    candidates: dict = field(default_factory=dict)
    commits: set = field(default_factory=set)

    def invalidate(self):
        for candidate in self.candidates.values():
            if candidate.state in {"running", "ready"}:
                candidate.state = "discarded"
            elif candidate.state == "adopted":
                candidate.state = "cancelled_after_adoption"

    def reset_answer(self):
        self.stages = {key: value for key, value in self.stages.items()
                       if key not in {"llm_first_text", "tts_first_packet", "audio_sent", "playback_observed"}}


def replay(scenario):
    """顺序检查已发生的合成事件；拒绝未知字段，不输出输入正文或身份。

    所有时间必须同一单调时钟域。传入事件是测试证据而非业务执行，违规只记
    固定码，不尝试修复、重试或调用任何下游。
    """
    if (not isinstance(scenario, dict) or set(scenario) - {"id", "condition", "clock_id", "events", "expected_violations"}
            or not _label(scenario.get("id")) or not _label(scenario.get("clock_id"))
            or scenario.get("condition") not in {"cold", "hot", "synthetic"}
            or not isinstance(scenario.get("events"), list) or len(scenario["events"]) > 4096):
        raise ValueError("replay_scenario_invalid")
    violations, turns = [], {}
    active, previous_time = None, -1
    usage = {"samples": 0, "unknown_samples": 0, "cache_reported_samples": 0}

    def fail(index, code):
        violations.append({"index": index, "code": code})

    for index, event in enumerate(scenario["events"]):
        if (not isinstance(event, dict) or set(event) - FIELDS or event.get("event") not in EVENTS
                or not _label(event.get("turn")) or not _number(event.get("at_ms"))
                or any(not _counter(event.get(key)) for key in IDENTITY)
                or ("candidate" in event and not _label(event["candidate"]))
                or ("duration_ms" in event and not _number(event["duration_ms"]))
                or any(key in event and event[key] is not None and not _counter(event[key])
                       for key in ("prompt_tokens", "cache_hit_tokens", "cache_miss_tokens", "output_tokens"))):
            fail(index, "event_schema_invalid")
            continue
        if event.get("clock_id", scenario["clock_id"]) != scenario["clock_id"]:
            fail(index, "clock_domain_mismatch")
            continue
        at = event["at_ms"]
        if at < previous_time:
            fail(index, "time_reversed")
            continue
        previous_time = at
        name, turn_id = event["event"], event["turn"]
        identity = tuple(event[key] for key in IDENTITY)
        if name == "turn_started":
            if turn_id in turns:
                fail(index, "turn_reused")
                continue
            if active is not None:
                turns[active].cancelled = True
                turns[active].invalidate()
            turns[turn_id] = Turn(identity)
            active = turn_id
            continue
        state = turns.get(turn_id)
        if state is None:
            fail(index, "turn_missing")
            continue
        if name == "candidate_cost":
            # 线程取消后仍可能运行；允许旧轮最终成本回报，不允许借此接管/发声。
            candidate = state.candidates.get(event.get("candidate"))
            if candidate is None or candidate.identity != identity or candidate.cost_recorded:
                fail(index, "candidate_cost_invalid")
            else:
                candidate.cost_recorded = True
                candidate.duration_ms = event.get("duration_ms")
                candidate.output_tokens = event.get("output_tokens")
            continue
        if turn_id != active:
            fail(index, "turn_superseded")
            continue
        if name == "cancelled":
            if identity[:2] != state.identity[:2] or identity[2] <= state.identity[2]:
                fail(index, "cancel_epoch_not_advanced")
                continue
            state.identity, state.cancelled = identity, True
            state.invalidate()
            continue
        if state.cancelled:
            fail(index, "after_cancel")
            continue
        if name == "resumed":
            if not (identity[0] > state.identity[0] and identity[1] == state.identity[1]
                    and identity[2] > state.identity[2]):
                fail(index, "resume_identity_not_advanced")
                continue
            state.identity, state.snapshot = identity, None
            state.final = state.confirmed = False
            state.stages.clear()
            state.invalidate()
            continue
        if name == "memory_changed":
            if not (identity[0] == state.identity[0] and identity[1] > state.identity[1]
                    and identity[2] > state.identity[2]):
                fail(index, "memory_change_not_invalidated")
                continue
            state.identity, state.snapshot = identity, None
            state.stages.pop("memory_snapshot", None)
            state.reset_answer()
            state.invalidate()
            continue
        if identity != state.identity:
            fail(index, "stale_identity")
            continue
        if name in {"user_end", "asr_final", "eou_confirmed", "memory_snapshot"}:
            if name == "user_end":
                # 最后一次尾声标注才是当前修订的起点，不累计多段独立耗时。
                state.stages[name] = at
            else:
                state.stages.setdefault(name, at)
            if name == "asr_final":
                state.final = True
            elif name == "eou_confirmed":
                state.confirmed = True
            elif name == "memory_snapshot":
                state.snapshot = identity
            continue
        if name.startswith("candidate_"):
            key = event.get("candidate")
            if key is None:
                fail(index, "candidate_missing")
                continue
            candidate = state.candidates.get(key)
            if name == "candidate_started":
                if candidate is not None or state.snapshot != identity:
                    fail(index, "candidate_start_invalid")
                else:
                    state.candidates[key] = Candidate(identity)
            elif candidate is None:
                fail(index, "candidate_missing")
            elif name == "candidate_ready":
                if candidate.state != "running":
                    fail(index, "candidate_transition_invalid")
                else:
                    candidate.state = "ready"
                    candidate.duration_ms = event.get("duration_ms")
                    candidate.output_tokens = event.get("output_tokens")
            elif name == "candidate_adopted":
                if (candidate.state != "ready" or candidate.identity != identity
                        or not state.final or not state.confirmed or state.snapshot != identity
                        or any(c.state == "adopted" for c in state.candidates.values())):
                    fail(index, "candidate_adoption_invalid")
                else:
                    candidate.state = "adopted"
            elif candidate.state in {"adopted", "discarded"}:
                fail(index, "candidate_transition_invalid")
            else:
                candidate.state = "discarded"
            continue
        if name in {"user_committed", "answer_committed", "tool_effect"}:
            if event.get("actor") != "formal":
                fail(index, "candidate_side_effect")
            elif not state.final or not state.confirmed:
                fail(index, "effect_before_confirmation")
            elif name in state.commits and name != "tool_effect":
                fail(index, "duplicate_commit")
            elif name == "answer_committed" and "audio_sent" not in state.stages:
                fail(index, "answer_commit_before_answer")
            else:
                state.commits.add(name)
            continue
        if name == "usage":
            usage["samples"] += 1
            prompt, hit, miss = (event.get(key) for key in ("prompt_tokens", "cache_hit_tokens", "cache_miss_tokens"))
            if prompt is None or event.get("output_tokens") is None:
                usage["unknown_samples"] += 1
            if hit is not None or miss is not None:
                if prompt is None or sum(value or 0 for value in (hit, miss)) > prompt:
                    fail(index, "cache_usage_invalid")
                else:
                    usage["cache_reported_samples"] += 1
            continue
        kind = event.get("kind")
        if kind not in {"answer", "waiting", "reasoning"}:
            fail(index, "content_kind_missing")
            continue
        if kind != "answer":
            if kind == "reasoning" and name != "llm_first_text":
                fail(index, "reasoning_reached_audio")
            continue  # 等待提示和推理均不产生首答指标。
        if name == "llm_first_text":
            candidate = state.candidates.get(event.get("candidate"))
            if event.get("candidate") is not None:
                if candidate is None or candidate.state not in {"running", "ready", "adopted"}:
                    fail(index, "candidate_transition_invalid")
                    continue
                # 推测阶段文本不能提前算成正式答案首字。
                if candidate.state != "adopted":
                    continue
        if not state.final or not state.confirmed or state.snapshot != identity:
            fail(index, "answer_before_confirmation")
            continue
        candidate_key = event.get("candidate")
        if candidate_key is not None and (candidate_key not in state.candidates
                or state.candidates[candidate_key].state != "adopted"):
            fail(index, "candidate_not_adopted")
            continue
        required = {"tts_first_packet": "llm_first_text", "audio_sent": "tts_first_packet",
                    "playback_observed": "audio_sent"}.get(name)
        if required is not None and required not in state.stages:
            fail(index, "stage_predecessor_missing")
            continue
        if name == "playback_observed" and event.get("evidence") != "synthetic_device_ack":
            fail(index, "playback_evidence_missing")
            continue
        state.stages.setdefault(name, at)

    rows, discarded, cancelled_after_adoption = [], [], 0
    for state in turns.values():
        for candidate in state.candidates.values():
            if candidate.state == "discarded":
                discarded.append(candidate)
            elif candidate.state == "cancelled_after_adoption":
                cancelled_after_adoption += 1
        start = state.stages.get("user_end")
        times = {key: (round(value - start, 3) if start is not None and value >= start else None)
                 for key, value in state.stages.items() if key in STAGES}
        rows.append({"cancelled": state.cancelled, "from_user_end_ms": times,
                     "snapshot_available_before_end": (start is not None and "memory_snapshot" in state.stages
                                                        and state.stages["memory_snapshot"] < start),
                     "actual_playback_proven": False,
                     "synthetic_playback_observed": "playback_observed" in state.stages})
    return {"scenario": scenario["id"], "condition": scenario["condition"],
            "violations": violations, "turns": rows, "usage": usage,
            "cancelled_after_adoption": cancelled_after_adoption,
            "discarded_candidates": {"count": len(discarded),
                "known_duration_ms": sum(c.duration_ms for c in discarded if c.duration_ms is not None),
                "unknown_duration_count": sum(c.duration_ms is None for c in discarded),
                "known_output_tokens": sum(c.output_tokens for c in discarded if c.output_tokens is not None),
                "unknown_output_tokens_count": sum(c.output_tokens is None for c in discarded)}}


def run_suite(document):
    if (not isinstance(document, dict) or set(document) != {"schema", "scenarios"}
            or document["schema"] != SCHEMA or not isinstance(document["scenarios"], list)
            or not 1 <= len(document["scenarios"]) <= 128):
        raise ValueError("replay_suite_invalid")
    reports, mismatches, seen = [], [], set()
    for scenario in document["scenarios"]:
        result = replay(scenario)
        if result["scenario"] in seen:
            raise ValueError("replay_scenario_duplicate")
        seen.add(result["scenario"])
        expected = scenario.get("expected_violations", [])
        if not isinstance(expected, list) or any(not _label(code) for code in expected):
            raise ValueError("replay_expectation_invalid")
        actual = [row["code"] for row in result["violations"]]
        if actual != expected:
            mismatches.append(result["scenario"])
        reports.append(result)
    groups = {}
    for condition in ("cold", "hot", "synthetic"):
        samples = [turn["from_user_end_ms"]["audio_sent"] for row in reports
                   if row["condition"] == condition and not row["violations"] for turn in row["turns"]
                   if not turn["cancelled"] and turn["from_user_end_ms"].get("audio_sent") is not None]
        groups[condition] = {"n": len(samples), "synthetic_send_median_ms": median(samples) if samples else None}
    return {"schema": SCHEMA, "evidence": "synthetic_replay_only", "matched": not mismatches,
            "mismatched_scenarios": mismatches, "groups": groups, "reports": reports,
            "limits": ["not_production_integration", "not_latency_benchmark", "no_actual_playback_proof",
                       "no_real_sdk_side_effect_proof", "no_p95_or_speedup_claim"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="仅传合成事件文件；不读取生产配置/日志")
    args = parser.parse_args(argv)
    try:
        with args.input.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("replay_file_too_large")
        document = json.loads(data.decode("utf-8"))
        report = run_suite(document)
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"error": "replay_input_invalid"}))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
