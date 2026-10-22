"""为固定 Xiaozhi 快照补齐直连 WebSocket protocol v2 音频封装。

默认 protocol v1 完全委托上游；只有握手头明确为 2 时才启用。该模块只
解决可配对时间戳的传输语义，不宣称 AEC 算法或自然打断质量已经通过。
"""

import struct
import time


HEADER = struct.Struct("!HHIII")
MAX_OPUS_BYTES = 8192
_LABEL_MODULUS = 2**32


def _next_audio_label(connection):
    """毫秒值仅作标签候选；同连接碰撞/回退时向前分配，不能当播放时钟。"""
    label = int(time.time() * 1000) % _LABEL_MODULUS
    previous = getattr(connection, "_longmemory_last_v2_audio_label", None)
    if previous is not None:
        distance = (label - previous) % _LABEL_MODULUS
        # 半环以内才视作正常向前（含自然回绕），否则是同毫秒或时钟回退。
        if distance == 0 or distance >= _LABEL_MODULUS // 2:
            label = (previous + 1) % _LABEL_MODULUS
    label = label or 1  # 0在接收端表示没有可配对参考，不能分配给有效音频。
    cache = getattr(connection, "aec_audio_cache", {})
    # 即使回绕到仍保留的旧标签，也不能覆盖另一包的实际解码参考。
    for _ in range(len(cache) + 1):
        if label not in cache:
            connection._longmemory_last_v2_audio_label = label
            return label
        label = (label + 1) % _LABEL_MODULUS or 1
    raise RuntimeError("v2_audio_label_space_exhausted")


def connection_protocol_version(connection):
    headers = getattr(connection, "headers", {})
    if not isinstance(headers, dict):
        return 1
    raw = next((value for key, value in headers.items()
                if isinstance(key, str) and key.lower() == "protocol-version"), "1")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def encode_v2_audio(payload, timestamp):
    payload = bytes(payload)
    if not payload or len(payload) > MAX_OPUS_BYTES or type(timestamp) is not int or not 0 <= timestamp < 2**32:
        raise ValueError("invalid_v2_audio")
    return HEADER.pack(2, 0, 0, timestamp, len(payload)) + payload


def decode_v2_audio(message):
    if not isinstance(message, bytes) or len(message) < HEADER.size:
        raise ValueError("invalid_v2_audio")
    version, message_type, reserved, timestamp, payload_size = HEADER.unpack_from(message)
    payload = message[HEADER.size:]
    if (version != 2 or message_type != 0 or reserved != 0
            or not payload or payload_size != len(payload) or payload_size > MAX_OPUS_BYTES):
        raise ValueError("invalid_v2_audio")
    return timestamp, payload


def install_direct_ws_v2(connection_class):
    """幂等包装固定上游的解码与发送入口，保留 v1/MQTT 原行为。"""
    if getattr(connection_class, "_longmemory_direct_ws_v2_installed", False):
        return

    original_decode = connection_class._decode_opus_packet

    def decode(connection, message):
        if (getattr(connection, "conn_from_mqtt_gateway", False)
                or connection_protocol_version(connection) != 2):
            return original_decode(connection, message)
        try:
            timestamp, payload = decode_v2_audio(message)
        except ValueError:
            connection.logger.bind(tag="direct-ws-v2").warning(
                "拒绝无效的 protocol v2 音频包"
            )
            return None
        pcm = original_decode(connection, payload)
        if pcm and timestamp > 0 and getattr(connection, "client_aec", False):
            pcm = connection._apply_aec(timestamp, pcm)
        return pcm

    connection_class._decode_opus_packet = decode
    connection_class._longmemory_direct_ws_v2_installed = True

    from core.handle import sendAudioHandle as audio_module
    if getattr(audio_module, "_longmemory_direct_ws_v2_installed", False):
        return
    original_send = audio_module._do_send_audio

    async def send(connection, opus_packet, flow_control):
        if (getattr(connection, "conn_from_mqtt_gateway", False)
                or connection_protocol_version(connection) != 2):
            return await original_send(connection, opus_packet, flow_control)

        timestamp = _next_audio_label(connection)
        if getattr(connection, "client_aec", False):
            # 与固定上游 MQTT AEC 路径使用相同的参考帧缓存格式。
            if not hasattr(connection, "aec_audio_cache"):
                import opuslib_next
                connection.aec_audio_cache = {}
                connection.aec_audio_cache_time = {}
                connection._send_opus_decoder = opuslib_next.Decoder(16000, 1)
            pcm = connection._send_opus_decoder.decode(bytes(opus_packet), 960)
            connection.aec_audio_cache[timestamp] = bytes(pcm)
            connection.aec_audio_cache_time[timestamp] = time.time()

        await connection.websocket.send(encode_v2_audio(opus_packet, timestamp))
        flow_control["packet_count"] = flow_control.get("packet_count", 0) + 1
        flow_control["sequence"] = flow_control.get("sequence", 0) + 1

    audio_module._do_send_audio = send
    audio_module._longmemory_direct_ws_v2_installed = True
