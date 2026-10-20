"""AD隔离窗口的CPU消费端：复用X编解码器，补真实缓冲取消与非静音帧观测。"""

import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time
from contextlib import contextmanager
from urllib.parse import urlsplit


def energy_qualified(pcm, sample_rate):
    """至少5ms的PCM样本超过固定幅值门；仅声学筛查，不证明语义或声质。"""
    values = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
    return sum(abs(value) >= 200 for value in values) >= (sample_rate + 199) // 200


def run(config):
    root = Path(__file__).resolve().parents[3]
    if Path(config["source_root"]).resolve() != root:
        raise ValueError("client_source_tree_mismatch")
    target = urlsplit(config["url"])
    if target.hostname != "127.0.0.1" or target.port in {8766, 8767, 8768, 8000, 8003, 18000, 18003, 18767, 18768, 18769, 18770}:
        raise ValueError("isolated_random_loopback_port_required")
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[:2] != ("127.0.0.1", target.port):
            raise RuntimeError("client_network_outside_owned_port")
        return connect(sock, address)
    def local_resolve(host, port, *args, **kwargs):
        if host != "127.0.0.1" or port != target.port:
            raise RuntimeError("client_dns_forbidden")
        return resolve(host, port, *args, **kwargs)
    socket.socket.connect, socket.getaddrinfo = local_connect, local_resolve
    sys.path[:0] = [str(root / "scripts/development/xiaozhi"), str(Path(config["voice_root"]))]
    native = Path(config["voice_root"]) / "native/libopus-1.6.1/Library/bin"
    os.environ["PATH"] = str(native) + os.pathsep + os.environ.get("PATH", "")
    owned_dll = os.add_dll_directory(str(native))
    import cosyvoice_streaming as consumer
    import opuslib_next
    spec = importlib.util.spec_from_file_location("ad_existing_opus_client", Path(__file__).with_name("benchmark_stream_client.py"))
    existing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(existing)
    original_install, original_buffer = consumer.install_cosyvoice_streaming, consumer.AdaptivePCMBuffer
    original_open, original_decoder = consumer._open_stream, opuslib_next.Decoder
    state = {"connection": None, "turn": None, "turns": [], "triggered": False, "reports": []}
    stage = config.get("cancel_stage")

    def trigger():
        if not state["triggered"]:
            state["triggered"] = True
            state["cancel_at"] = time.perf_counter()
            state["connection"].client_abort = True

    def install(tts, connection):
        state["connection"] = connection
        def record(report, **_kwargs):
            state["reports"].append(report)
        connection._longmemory_voice_latency = type("BenchTelemetry", (), {"record_continuity": staticmethod(record)})()
        original_install(tts, connection)
        stream = tts.to_tts_stream
        def observed(text, opus_handler=None):
            turn = state["turn"]
            if turn is None or turn["sentence_id"] != connection.sentence_id:
                turn = {"sentence_id": connection.sentence_id, "started": time.perf_counter(),
                        "first_energy_qualified_opus_ms": None, "packets_after_cancel": 0}
                state["turn"] = turn
                state["turns"].append(turn)
            def packet(value):
                if state["triggered"] and len(state["turns"]) == 1:
                    turn["packets_after_cancel"] += 1
                opus_handler(value)
                if stage == "after_audio" and connection.client_abort and not state["triggered"]:
                    state["triggered"] = True
                    state["cancel_at"] = time.perf_counter()
            result = stream(text, opus_handler=packet)
            if state["triggered"] and len(state["turns"]) == 1:
                turn["cancel_to_client_return_ms"] = (time.perf_counter() - state["cancel_at"]) * 1000
            return result
        tts.to_tts_stream = observed

    class Buffer(original_buffer):
        def _put(self, pcm):
            super()._put(pcm)
            if stage == "buffering" and not state["triggered"]:
                trigger()

    @contextmanager
    def opened(*args, **kwargs):
        with original_open(*args, **kwargs) as response:
            if stage == "before_audio" and not state["triggered"]:
                trigger()
            yield response

    class Decoder:
        def __init__(self, rate, channels):
            self.inner, self.rate = original_decoder(rate, channels), rate
        def decode(self, *args, **kwargs):
            pcm = self.inner.decode(*args, **kwargs)
            turn = state["turn"]
            if turn["first_energy_qualified_opus_ms"] is None and energy_qualified(pcm, self.rate):
                turn["first_energy_qualified_opus_ms"] = (time.perf_counter() - turn["started"]) * 1000
            return pcm

    consumer.install_cosyvoice_streaming, consumer.AdaptivePCMBuffer = install, Buffer
    consumer._open_stream, opuslib_next.Decoder = opened, Decoder
    try:
        # X消费端的同一编码器取消后新轮入口保持，前三种取消都安排随后正常一轮。
        request = {**config, "cancel_after_packets": 3 if stage else None}
        result = existing.run(request)
        if stage and not state["triggered"]:
            raise AssertionError("requested_cancel_boundary_not_reached")
        for row, turn in zip(result["rounds"], state["turns"]):
            row["client_tts_wall_rtf"] = row.pop("rtf")
            cursor = row["first_opus_ms"]
            if cursor is not None:
                for at in row["packet_arrivals_ms"]:
                    cursor = max(cursor, at) + 60
            row["estimated_playback_end_ms"] = cursor
            row["first_energy_qualified_opus_ms"] = turn["first_energy_qualified_opus_ms"]
            row["packets_after_cancel"] = turn["packets_after_cancel"]
            row["cancel_to_client_return_ms"] = turn.get("cancel_to_client_return_ms")
        result.update(continuity=state["reports"], cancel_stage=stage,
                      evidence_kind="isolated_tts_transport_not_device_or_full_chain",
                      energy_gate={"minimum_ms": 5, "absolute_pcm16_threshold": 200,
                                   "semantic_answer_verified": False},
                      timing_origin="first_tts_segment_text_already_ready",
                      gpu_work_performed=False,
                      llm_first_output_used_as_text=False)
        return result
    finally:
        consumer.install_cosyvoice_streaming, consumer.AdaptivePCMBuffer = original_install, original_buffer
        consumer._open_stream, opuslib_next.Decoder = original_open, original_decoder
        socket.socket.connect, socket.getaddrinfo = connect, resolve
        owned_dll.close()


if __name__ == "__main__":
    print(json.dumps(run(json.loads(sys.stdin.buffer.read())), ensure_ascii=False))
