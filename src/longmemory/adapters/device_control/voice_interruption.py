"""进程内音频撤权摘要的有限投影；不把配置/发送返回解释为设备播放。"""

from .protocol import BridgeError

COUNTERS = frozenset({
    "asr_handoff", "asr_handoff_revoked", "upstream_abort_revoked", "queues_cleared",
    "abort_call_returned", "connection_closed", "tts_started", "tts_returned",
    "first_segment_callback_returned", "first_answer_send_returned", "answer_send_returned",
    "cue_send_returned", "stale_packet_dropped", "inflight_old_send_returned",
    "stale_message_dropped", "stale_stop_dropped", "normal_stop_returned",
    "producer_adaptive_buffer", "producer_incremental_pcm", "producer_buffered_pcm",
    "producer_preset", "producer_complete_wav_fallback",
})
_REQUEST_MODES = {"adaptive_buffer": "incremental", "incremental_pcm": "incremental",
                  "buffered_pcm": "buffered", "preset": None, "complete_wav_fallback": "full_wav"}
_FIELDS = {"version", "enabled", "connection_present", "installed", "status", "epoch",
           "active_output", "active_tts_calls", "closed", "configuration", "observed", "counts",
           "last_stage", "device_playback_acknowledged"}


def _integer(value):
    # 保留准确非负计数，避免JavaScript精度丢失；不把非法值修补为0。
    return type(value) is int and 0 <= value <= 9007199254740991


def voice_interruption(value):
    def reject():
        raise BridgeError("bridge_invalid_response", 502)
    if type(value) is not dict or set(value) != _FIELDS or type(value["version"]) is not int or value["version"] != 1:
        reject()
    if any(type(value[name]) is not bool for name in (
            "enabled", "connection_present", "installed", "active_output", "closed")) or value["device_playback_acknowledged"] is not False:
        reject()
    if not _integer(value["active_tts_calls"]):
        reject()
    counts = value["counts"]
    if type(counts) is not dict or set(counts) != COUNTERS or not all(_integer(n) for n in counts.values()):
        reject()
    config = value["configuration"]
    if (type(config) is not dict or set(config) != {"delivery_mode", "value_kind"}
            or config["value_kind"] != "configuration" or type(config["delivery_mode"]) not in {str, type(None)}):
        reject()
    if config["delivery_mode"] not in ({"buffered", "incremental", "adaptive", "unknown"} if value["enabled"] else {None}):
        reject()
    if value["connection_present"]:
        if not _integer(value["epoch"]):
            reject()
        status = "not_installed" if not value["installed"] else "observed" if any(counts.values()) else "idle_no_samples"
    else:
        status = "no_connection"
        if (value["epoch"] is not None or value["enabled"] or value["installed"] or value["closed"]
                or value["active_output"] or value["active_tts_calls"] or any(counts.values())
                or value["observed"] is not None or value["last_stage"] is not None):
            reject()
    if value["status"] != status:
        reject()
    observed = value["observed"]
    if observed is not None:
        fields = {"value_kind", "producer_path", "request_delivery_mode", "v2_transport_confirmed",
                  "server_model_delivery_mode", "server_reply_cache_hit"}
        if (type(observed) is not dict or set(observed) != fields
                or observed["value_kind"] != "observed_client_branch"
                or type(observed["producer_path"]) is not str or observed["producer_path"] not in _REQUEST_MODES
                or observed["request_delivery_mode"] != _REQUEST_MODES[observed["producer_path"]]
                or type(observed["v2_transport_confirmed"]) is not bool
                or observed["server_model_delivery_mode"] != "unconfirmed"
                or observed["server_reply_cache_hit"] != "unconfirmed"):
            reject()
        if counts["producer_" + observed["producer_path"]] == 0:
            reject()
        if observed["producer_path"] in {"preset", "complete_wav_fallback"} and observed["v2_transport_confirmed"]:
            reject()
    stage = value["last_stage"]
    if stage is not None:
        if (type(stage) is not dict or set(stage) != {"event", "at_ms", "epoch"}
                or type(stage["event"]) is not str or stage["event"] not in COUNTERS
                or not _integer(stage["at_ms"]) or not _integer(stage["epoch"])
                or value["epoch"] is None or stage["epoch"] > value["epoch"] or counts[stage["event"]] == 0):
            reject()
    return {**value, "configuration": dict(config), "counts": dict(counts),
            "observed": None if observed is None else dict(observed),
            "last_stage": None if stage is None else dict(stage)}
