"""宿主/小智共同候选RPC契约；不接受SDK令牌、供应商凭据或来源写操作。"""

import re
from uuid import UUID


ACTIONS = ("snapshot", "start", "confirm", "cancel", "close")
BODY_LIMIT = 192 * 1024
BASE_FIELDS = {"version", "connection_id", "turn_id", "transcript_revision", "cancel_epoch"}
EXTRA_FIELDS = {
    "snapshot": {"query", "session_id"},
    "start": {"snapshot_id", "messages", "tools_required"},
    "confirm": {"snapshot_id", "query", "messages", "tools_required", "formal_turn_id", "client_round_id", "session_id"},
    "cancel": set(), "close": set(),
}


def _hex(value, minimum=32, maximum=32):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d,%d}" % (minimum, maximum), value) is not None


def validate_voice_proposal_request(action, value):
    invalid = ValueError("voice_proposal_request_invalid")
    if (action not in ACTIONS or not isinstance(value, dict)
            or set(value) != BASE_FIELDS | EXTRA_FIELDS[action]
            or type(value["version"]) is not int or value["version"] != 1
            or not _hex(value["connection_id"])
            or any(type(value[key]) is not int or not 0 <= value[key] < 2**63
                   for key in ("turn_id", "transcript_revision", "cancel_epoch"))):
        raise invalid
    if "query" in value and (not isinstance(value["query"], str) or not value["query"].strip() or len(value["query"]) > 16000):
        raise invalid
    if any(key in value and not _hex(value[key]) for key in ("session_id", "snapshot_id")):
        raise invalid
    if "client_round_id" in value and not _hex(value["client_round_id"], 24, 32):
        raise invalid
    if "formal_turn_id" in value:
        try:
            if not isinstance(value["formal_turn_id"], str) or str(UUID(value["formal_turn_id"])) != value["formal_turn_id"]:
                raise invalid
        except (ValueError, TypeError, AttributeError):
            raise invalid from None
    if "messages" in value:
        rows = value["messages"]
        if (not isinstance(rows, list) or not 1 <= len(rows) <= 128
                or any(not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
                       or row[0] not in {"system", "user", "assistant"}
                       or not isinstance(row[1], str) for row in rows)
                or rows[0][0] != "system" or any(row[0] == "system" for row in rows[1:])
                or sum(len(row[1]) for row in rows) > 32000 or type(value["tools_required"]) is not bool):
            raise invalid
    try:
        if "query" in value:
            value["query"].encode("utf-8")
        for row in value.get("messages", []):
            row[1].encode("utf-8")
    except UnicodeError:
        raise invalid from None
    return value


def validate_voice_proposal_response(action, value):
    invalid = RuntimeError("voice_proposal_response_invalid")
    fields = {"snapshot": {"snapshot_id", "memory_context", "reason_code"},
              "start": {"reason_code"}, "confirm": {"text", "reason_code"},
              "cancel": {"owned_upstream_exited", "provider_compute_stopped"},
              "close": {"owned_upstream_exited", "provider_compute_stopped"}}
    states = {"snapshot": {"ready", "unavailable"}, "start": {"preparing", "miss"},
              "confirm": {"adopted", "miss"}, "cancel": {"cancelled", "closing"}, "close": {"closed", "closing"}}
    if (action not in ACTIONS or not isinstance(value, dict) or set(value) != {"version", "state"} | fields[action]
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["state"], str) or value["state"] not in states[action]):
        raise invalid
    reason = value.get("reason_code")
    if reason is not None and (not isinstance(reason, str) or re.fullmatch(r"[a-z0-9_-]{1,128}", reason) is None):
        raise invalid
    if action == "snapshot":
        if value["state"] == "ready":
            if (not _hex(value["snapshot_id"]) or not isinstance(value["memory_context"], str)
                    or len(value["memory_context"]) > 32000):
                raise invalid
        elif value["snapshot_id"] is not None or value["memory_context"] is not None:
            raise invalid
    if action == "confirm":
        if value["state"] == "adopted":
            if not isinstance(value["text"], str) or not value["text"].strip() or len(value["text"]) > 16000:
                raise invalid
        elif value["text"] is not None:
            raise invalid
    if action in {"cancel", "close"}:
        if (type(value["owned_upstream_exited"]) is not bool or value["provider_compute_stopped"] is not False
                or (value["state"] == "closing") == value["owned_upstream_exited"]):
            raise invalid
    return value
