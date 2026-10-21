"""只读显式打断协议摘要；协商/写出返回不代表物理播放确认。"""

from .protocol import BridgeError

COUNTERS = frozenset({"hello_confirmed", "start_sent", "audio_sent", "subtitle_sent", "eos_sent",
                      "interrupt_sent", "stale_dropped", "unowned_dropped", "send_timeout", "closed"})
_FIELDS = {"version", "state", "negotiated", "reason", "counts", "active_writes",
           "device_playback_acknowledged"}
_CLOSE_REASONS = {"epoch_exhausted", "connection_closed", "send_timeout", "gate_timeout",
                  "cancelled_write_unsettled", "send_failed", "mode_changed"}


def tts_interrupt(value):
    def reject():
        raise BridgeError("bridge_invalid_response", 502)
    if (type(value) is not dict or set(value) != _FIELDS
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["negotiated"]) is not bool
            or value["device_playback_acknowledged"] is not False):
        reject()
    def integer(number):
        return type(number) is int and 0 <= number <= 9007199254740991
    counts = value["counts"]
    if (type(counts) is not dict or set(counts) != COUNTERS
            or not all(integer(n) for n in counts.values()) or not integer(value["active_writes"])):
        reject()
    state, reason = value["state"], value["reason"]
    if type(state) is not str or type(reason) is not str:
        reject()
    if state in {"no_connection", "not_installed"}:
        if reason != state or value["negotiated"] or value["active_writes"] or any(counts.values()):
            reject()
    elif state == "closed":
        if reason not in _CLOSE_REASONS or counts["closed"] == 0:
            reject()
    elif state in {"hello_pending", "legacy", "negotiated"}:
        expected = {"hello_pending":"hello_pending", "legacy":"legacy_not_confirmed", "negotiated":"confirmed"}
        if (reason != expected[state] or value["negotiated"] != (state == "negotiated") or counts["closed"]):
            reject()
        if state == "negotiated":
            if counts["hello_confirmed"] == 0:
                reject()
        elif any(counts.values()):
            reject()
    else:
        reject()
    return {**value, "counts": dict(counts)}
