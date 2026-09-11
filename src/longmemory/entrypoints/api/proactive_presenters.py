"""主动交流领域对象到公开 JSON 的纯投影。

这些函数不打开数据库、不调用设备，也不修改传入对象。把展示契约集中在这里后，
主动交流的调度与持久化代码可以在后续切片中独立迁移。
"""

import hashlib
from datetime import datetime, timedelta, timezone


def proactive_policy_json(settings):
    config = settings.config
    return {
        "subject_id": settings.subject_id,
        "enabled": config.enabled,
        "utc_offset_minutes": config.utc_offset_minutes,
        "allowed_weekdays": list(config.allowed_weekdays),
        "allowed_start_minute": config.allowed_start_minute,
        "allowed_end_minute": config.allowed_end_minute,
        "daily_limit": config.daily_limit,
        "minimum_interval_seconds": int(config.minimum_interval.total_seconds()),
        "maximum_lifetime_seconds": int(config.maximum_lifetime.total_seconds()),
        "quiet_until": settings.quiet_until.isoformat() if settings.quiet_until else None,
        "policy_version": config.policy_version,
        "revision": settings.revision,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
        "automatic_enabled": settings.automatic_enabled,
        "scheduled_minute": settings.scheduled_minute,
        "greeting_text": settings.greeting_text,
        "topic_enabled": settings.topic_enabled,
    }


def topic_seed_json(row, *, now):
    valid_from = (
        datetime.fromisoformat(row["scenario_valid_from"])
        if row["scenario_valid_from"] else None
    )
    valid_to = (
        datetime.fromisoformat(row["scenario_valid_to"])
        if row["scenario_valid_to"] else None
    )
    return {
        "id": row["id"], "subject_id": row["subject_id"],
        "scenario_id": row["scenario_id"], "prompt_text": row["prompt_text"],
        "status": row["status"], "created_at": row["created_at"],
        "updated_at": row["updated_at"], "revision": row["revision"],
        "source": {
            "layer": "l2", "title": row["scenario_title"],
            "summary": row["scenario_summary"],
            "status": row["scenario_status"],
        },
        "usable": (
            row["status"] == "active" and row["scenario_status"] == "active"
            and (valid_from is None or valid_from <= now)
            and (valid_to is None or valid_to > now)
        ),
    }


def follow_up_json(row, *, now):
    source_digest = hashlib.sha256(row["source_content"].encode("utf-8")).hexdigest()
    follow_up_at = datetime.fromisoformat(row["follow_up_at"])
    source_current = (
        row["source_retired_at"] is None
        and (
            row["source_valid_from"] is None
            or datetime.fromisoformat(row["source_valid_from"]) <= follow_up_at
        )
        and (
            row["source_valid_to"] is None
            or datetime.fromisoformat(row["source_valid_to"]) > follow_up_at
        )
        and source_digest == row["source_content_sha256"]
    )
    outreach_id = row.get("outreach_id")
    return {
        "id": row["id"], "subject_id": row["subject_id"],
        "source_memory_id": row["source_memory_id"],
        "prompt_text": row["prompt_text"], "follow_up_at": row["follow_up_at"],
        "status": row["status"], "created_at": row["created_at"],
        "updated_at": row["updated_at"], "revision": row["revision"],
        "creation_kind": row["creation_kind"],
        "source_message_id": row["source_message_id"],
        "source": {
            "layer": "l1", "content": row["source_content"],
            "state": "retired" if row["source_retired_at"] else "active",
            "superseded_by_id": row["source_superseded_by_id"],
        },
        "activation": None if outreach_id is None else {
            "outreach_id": outreach_id,
            "state": row["outreach_state"],
            "revision": row["outreach_revision"],
            "expires_at": row["outreach_expires_at"],
        },
        "due": follow_up_at <= now,
        "ready_for_activation": (
            row["status"] == "candidate" and source_current
            and follow_up_at > now and outreach_id is None
        ),
        "blocked_reason": (
            "cancelled" if row["status"] == "cancelled"
            else "already_activated" if outreach_id is not None
            else "source_changed" if not source_current
            else "time_reached" if follow_up_at <= now
            else None
        ),
    }


def outreach_result_json(outreach, *, replayed, decision=None, delivery=None, device=None):
    return {
        "outreach_id": outreach.id,
        "state": outreach.state.value,
        "revision": outreach.revision,
        "replayed": replayed,
        "policy_action": decision.action.value if decision else None,
        "policy_reason": decision.reason.value if decision else None,
        "delivery_reason": delivery.reason_code if delivery else None,
        "device": None if device is None else {
            "ready": device.ready,
            "user_session_active": device.user_session_active,
            "reason": device.reason_code,
        },
    }


def strategy_candidate_json(candidate, store):
    local_zone = timezone(timedelta(minutes=candidate.utc_offset_minutes))
    sources = []
    for source in store.list_sources(candidate.id):
        local = datetime.fromisoformat(source["queued_at"]).astimezone(local_zone)
        sources.append({
            **source,
            "local_date": local.date().isoformat(),
            "local_minute": local.hour * 60 + local.minute,
        })
    return {
        "id": candidate.id,
        "subject_id": candidate.subject_id,
        "status": candidate.status.value,
        "suggested_minute": candidate.suggested_minute,
        "utc_offset_minutes": candidate.utc_offset_minutes,
        "evidence_count": candidate.evidence_count,
        "distinct_local_dates": candidate.distinct_local_dates,
        "rationale_code": candidate.rationale_code,
        "generator_version": candidate.generator_version,
        "created_at": candidate.created_at.isoformat(),
        "updated_at": candidate.updated_at.isoformat(),
        "revision": candidate.revision,
        "active": False,
        "sources": sources,
    }


def routine_candidate_json(candidate, store):
    local_zone = timezone(timedelta(minutes=candidate.utc_offset_minutes))
    sources = []
    for source in store.list_sources(candidate.id):
        local = datetime.fromisoformat(source["occurred_at"]).astimezone(local_zone)
        sources.append({
            **source,
            "local_date": local.date().isoformat(),
            "local_minute": local.hour * 60 + local.minute,
        })
    return {
        "id": candidate.id,
        "subject_id": candidate.subject_id,
        "status": candidate.status.value,
        "expected_minute": candidate.expected_minute,
        "utc_offset_minutes": candidate.utc_offset_minutes,
        "observation_window_minutes": candidate.observation_window_minutes,
        "evidence_count": candidate.evidence_count,
        "distinct_local_dates": candidate.distinct_local_dates,
        "rationale_code": candidate.rationale_code,
        "generator_version": candidate.generator_version,
        "created_at": candidate.created_at.isoformat(),
        "updated_at": candidate.updated_at.isoformat(),
        "revision": candidate.revision,
        "active": False,
        "sources": sources,
    }


def absence_strategy_version_json(version, *, active=False):
    return {
        "id": version.id,
        "subject_id": version.subject_id,
        "source_candidate_id": version.source_candidate_id,
        "source_candidate_revision": version.source_candidate_revision,
        "expected_minute": version.expected_minute,
        "grace_minutes": version.grace_minutes,
        "utc_offset_minutes": version.utc_offset_minutes,
        "allowed_weekdays": list(version.allowed_weekdays),
        "trigger_policy_version": version.trigger_policy_version,
        "replay_protocol": version.replay_protocol,
        "replay_dataset_name": version.replay_dataset_name,
        "replay_dataset_version": version.replay_dataset_version,
        "replay_dataset_sha256": version.replay_dataset_sha256,
        "parameter_fingerprint": version.parameter_fingerprint,
        "replay_case_count": version.replay_case_count,
        "replay_matched_count": version.replay_matched_count,
        "replay_unsafe_allow_count": version.replay_unsafe_allow_count,
        "replay_gate_passed": version.replay_gate_passed,
        "replayed_at": version.replayed_at.isoformat(),
        "created_at": version.created_at.isoformat(),
        "active": active,
    }


def absence_selection_json(selection):
    if selection is None:
        return {"current_version_id": None, "revision": 0, "updated_at": None}
    return {
        "current_version_id": selection.version_id,
        "revision": selection.revision,
        "updated_at": selection.updated_at.isoformat(),
    }


def absence_switch_event_json(event):
    return {
        "id": event.id,
        "previous_version_id": event.previous_version_id,
        "selected_version_id": event.selected_version_id,
        "action": event.action.value,
        "pointer_revision": event.pointer_revision,
        "created_at": event.created_at.isoformat(),
    }
