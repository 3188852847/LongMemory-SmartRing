"""豆包 3.0 JSON WebSocket 客户端，协议来源见下方官方文档。

https://docs.volcengine.com/docs/6561/2549778?lang=zh
https://docs.volcengine.com/docs/6561/2549732?lang=zh

此模块只处理传输与会话事件，不保存音频、转写或供应商会话 ID，也不接
个人记忆。3.0 的 PCM 输出为 24 kHz/int16；不能套用旧版 PCM32 配置。
"""

import asyncio
import base64
import binascii
from dataclasses import dataclass, field
import json
import time
from typing import AsyncIterator
from uuid import uuid4

from .config import DoubaoConfig


class RealtimeError(RuntimeError):
    """固定错误码；避免第三方异常正文携带 HTTP 请求头或用户内容。"""


@dataclass(frozen=True)
class RealtimeEvent:
    kind: str
    text: str = field(default="", repr=False)
    audio: bytes = field(default=b"", repr=False)
    question_id: str = ""
    response_id: str = ""
    item_id: str = ""
    is_final: bool = False
    code: str = ""
    tts_type: str = ""

    def get(self, name, default=None):
        return getattr(self, name, default)


def session_payload(config: DoubaoConfig) -> dict:
    """仅声明本阶段用到的官方字段；不自动加载历史或声明记忆工具。"""
    return {
        "type": "session.create",
        "session": {
            "model": config.model,
            "instructions": config.instructions,
            "audio": {
                "input": {"format": {"type": "pcm", "rate": 16000}},
                "output": {
                    "format": {"type": "pcm", "rate": 24000},
                    "voice": config.speaker, "speed": 0, "loudness": 0,
                },
            },
        },
        "extension": {"asr": {}, "tts": {}, "dialog": {}},
    }


def _string(payload: dict, key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise RealtimeError("realtime_invalid_event")
    return value


class DoubaoRealtimeClient:
    """每个设备连接独享实例；单一接收协程避免多个消费者争抢云端帧。"""

    def __init__(self, config: DoubaoConfig, *, connect_factory=None,
                 timeout: float = 10.0, close_timeout: float = 2.0,
                 queue_limit: int = 256, clock=None, sleep=None):
        self.config = config
        self._connect_factory = connect_factory
        self.timeout = timeout
        self.close_timeout = close_timeout
        self._queue = asyncio.Queue(maxsize=queue_limit)
        self._socket = None
        self._reader = None
        self._session_ready = None
        self._session_closed = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._audio_lock = asyncio.Lock()
        self._cancel_lock = asyncio.Lock()
        self._cancel_ack = None
        self._cancel_response_id = ""
        self._closing = False
        self._closed = False
        self._listening = False
        self._audio_tail = bytearray()
        self._next_audio_time = 0.0
        self._last_audio_time = None
        self._active_response = ""
        self._retired = set()
        self._retired_order = []
        self._pending_start = None
        self._waiting_for_response = False
        self._response_id_seen = False
        self._suppress_until_speech = False
        self._clock = clock
        self._sleep = sleep or asyncio.sleep

    async def connect(self) -> None:
        if self._socket is not None or self._closed:
            raise RealtimeError("realtime_client_not_reusable")
        factory = self._connect_factory
        if factory is None:
            try:
                # 小智环境已固定 websockets 14.2；离线配置检查不导入依赖。
                from websockets.asyncio.client import connect
            except ImportError:
                raise RealtimeError("realtime_dependency_missing") from None
            factory = connect
        loop = asyncio.get_running_loop()
        self._session_ready = loop.create_future()
        try:
            self._socket = await factory(
                self.config.url, additional_headers={"X-Api-Key": self.config.api_key},
                open_timeout=self.timeout, close_timeout=self.close_timeout,
                max_size=4 * 1024 * 1024,
            )
            self._reader = asyncio.create_task(self._read_loop())
            await self._send(session_payload(self.config))
            await asyncio.wait_for(asyncio.shield(self._session_ready), self.timeout)
            # 会话建立时设备未必已开麦；显式静音维持官方模型输入链路。
            await self._send({"type": "input_audio_mute.commit"})
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception:
            await self.close()
            raise RealtimeError("realtime_connect_failed") from None

    async def _send(self, payload: dict, *, closing: bool = False) -> None:
        if self._socket is None or self._closed or (self._closing and not closing):
            raise RealtimeError("realtime_not_connected")
        frame = json.dumps({"event_id": uuid4().hex, **payload}, ensure_ascii=False)

        async def send_locked():
            async with self._send_lock:
                await self._socket.send(frame)

        try:
            # 超时包含等锁的时间；否则close会卡在另一条尚未完成的上传之后。
            await asyncio.wait_for(send_locked(), self.close_timeout if closing else self.timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise RealtimeError("realtime_send_failed") from None

    async def start_listening(self) -> None:
        async with self._audio_lock:
            if not self._listening:
                await self._send({"type": "input_audio_unmute.commit"})
                self._listening = True
                self._next_audio_time = 0.0
                self._last_audio_time = None

    async def _audio_packet(self, packet: bytes) -> None:
        # 小智的 Windows Python 3.10 monotonic 使用15.6ms粒度的计数器，
        # 与20ms音频包过于接近；perf_counter为现有系统高精度单调时钟。
        now = self._clock or time.perf_counter
        deadline = self._next_audio_time or now()
        # 以固定deadline递增补偿小幅定时器/发送抖动，不能把每次overshoot
        # 永久加入下一包；大于两包的调度停顿则重置，避免长阻塞后突发追赶。
        if now() - deadline > 0.040:
            deadline = now()
        wake_deadline = deadline
        if self._last_audio_time is not None:
            # 小幅追赶最多缩短半帧，不允许同一时刻突发补发旧包。
            wake_deadline = max(wake_deadline, self._last_audio_time + 0.010)
        delay = wake_deadline - now()
        while delay > 0:
            await self._sleep(delay)
            # 旧Windows事件循环可能提前唤醒，按高精度时钟再次核对。
            delay = wake_deadline - now()
        self._last_audio_time = now()
        await self._send({"type": "input_audio_buffer.append",
                          "audio": base64.b64encode(packet).decode("ascii")})
        self._next_audio_time = deadline + 0.020
        if now() - self._next_audio_time > 0.040:
            self._next_audio_time = now() + 0.020

    async def send_audio(self, pcm: bytes) -> None:
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 32000:
            raise RealtimeError("realtime_invalid_input_audio")
        async with self._audio_lock:
            if not self._listening:
                raise RealtimeError("realtime_microphone_muted")
            self._audio_tail.extend(pcm)
            while len(self._audio_tail) >= 640:
                packet = bytes(self._audio_tail[:640])
                del self._audio_tail[:640]
                await self._audio_packet(packet)

    async def _flush_audio(self) -> None:
        # 最后一帧不足20ms时只补本帧静音，不生成或保存额外录音文件。
        if self._audio_tail:
            packet = bytes(self._audio_tail).ljust(640, b"\0")
            self._audio_tail.clear()
            await self._audio_packet(packet)

    async def stop_listening(self) -> None:
        async with self._audio_lock:
            if self._listening:
                await self._flush_audio()
                await self._send({"type": "input_audio_mute.commit"})
                self._listening = False

    async def commit(self) -> None:
        """强制判停；与 session.close（结束整个会话）不同。"""
        async with self._audio_lock:
            await self._flush_audio()
            await self._send({"type": "input_audio_buffer.commit"})

    async def say_text(self, text: str) -> None:
        """官方打招呼/直接播报入口；不把它冒充向模型发送文本问题。"""
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise RealtimeError("realtime_invalid_speech_text")
        await self._send({"type": "speech_text_buffer.commit", "text": text})

    async def send_text(self, text: str) -> None:
        """兼容桥的文本发送方法；语义与 say_text 一致，直接播报文本。"""
        await self.say_text(text)

    def _retire(self, response_id: str) -> None:
        if response_id and response_id not in self._retired:
            self._retired.add(response_id)
            self._retired_order.append(response_id)
            if len(self._retired_order) > 256:
                self._retired.discard(self._retired_order.pop(0))

    async def interrupt(self) -> None:
        """先失效本地回答，再等待无ID的取消确认；串行请求避免确认错配。"""
        async with self._cancel_lock:
            self._cancel_response_id = self._active_response
            self._retire(self._active_response)
            self._active_response = ""
            self._pending_start = None
            self._suppress_until_speech = True
            self._cancel_ack = asyncio.get_running_loop().create_future()
            await self._send({"type": "response.cancel"})
            try:
                await asyncio.wait_for(asyncio.shield(self._cancel_ack), self.timeout)
            except asyncio.TimeoutError:
                # 无法确认取消时不继续打开新一轮；断开后由用户重连。
                await self.close()
                raise RealtimeError("realtime_cancel_timeout") from None
            finally:
                self._cancel_ack = None
                self._cancel_response_id = ""

    def _emit(self, event: RealtimeEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            raise RealtimeError("realtime_event_overflow") from None

    def _response_start(self, payload: dict, response_id: str) -> bool:
        if not response_id or response_id in self._retired or self._suppress_until_speech:
            return False
        self._response_id_seen = True
        if response_id != self._active_response:
            self._retire(self._active_response)
            self._active_response = response_id
            self._emit(RealtimeEvent("response_started", response_id=response_id,
                                    question_id=_string(payload, "question_id"),
                                    tts_type=_string(payload, "tts_type")))
        return True

    def _handle(self, payload: dict) -> None:
        event_type = _string(payload, "type")
        if event_type == "session.created":
            if self._session_ready and not self._session_ready.done():
                self._session_ready.set_result(None)
        elif event_type == "session.closed":
            self._session_closed.set()
        elif event_type == "response.canceled":
            # 3.0 ack没有response_id；只归给本次串行cancel捕获的旧回答。
            if self._cancel_ack is not None and not self._cancel_ack.done():
                if self._cancel_response_id:
                    self._emit(RealtimeEvent("canceled", response_id=self._cancel_response_id))
                self._cancel_ack.set_result(None)
        elif event_type == "conversation.item.input_audio_transcription.started":
            if self._waiting_for_response and not self._response_id_seen:
                # 旧回答尚无ID时无法证明下一条started属于新问题。官方没有
                # 承诺ASR.item_id等于audio.question_id，因此关闭而非猜测归属。
                raise RealtimeError("realtime_turn_ambiguous")
            self._retire(self._active_response)
            self._active_response = ""
            self._pending_start = None
            self._waiting_for_response = False
            self._response_id_seen = False
            self._suppress_until_speech = False
            self._emit(RealtimeEvent("speech_started", item_id=_string(payload, "item_id")))
        elif event_type in {"conversation.item.input_audio_transcription.delta",
                            "conversation.item.input_audio_transcription.completed"}:
            final = event_type.endswith(".completed")
            text = _string(payload, "transcript" if final else "delta")
            if final and text.strip():
                self._waiting_for_response = True
            self._emit(RealtimeEvent("transcript", item_id=_string(payload, "item_id"),
                                    text=text,
                                    is_final=final))
        elif event_type == "response.output_audio.started":
            if self._suppress_until_speech:
                self._retire(_string(payload, "response_id"))
                return
            response_id = _string(payload, "response_id")
            if response_id:
                self._response_start(payload, response_id)
            else:
                # 官方起始示例允许空ID，首个带ID的delta才建立本地输出身份。
                self._pending_start = payload
        elif event_type in {"response.output_audio.delta", "response.output_text.delta"}:
            response_id = _string(payload, "response_id")
            if self._pending_start is not None:
                pending = self._pending_start
                self._pending_start = None
                self._response_start({**pending, "question_id": _string(payload, "question_id")},
                                     response_id)
            if (self._suppress_until_speech or not response_id
                    or response_id != self._active_response or response_id in self._retired):
                return
            fields = {"question_id": _string(payload, "question_id"), "response_id": response_id}
            if event_type == "response.output_audio.delta":
                try:
                    pcm = base64.b64decode(_string(payload, "delta"), validate=True)
                except (ValueError, binascii.Error):
                    raise RealtimeError("realtime_invalid_output_audio") from None
                if not pcm or len(pcm) % 2 or len(pcm) > 192000:
                    raise RealtimeError("realtime_invalid_output_audio")
                self._emit(RealtimeEvent("audio", audio=pcm, **fields))
            else:
                self._emit(RealtimeEvent("text", text=_string(payload, "delta"), **fields))
        elif event_type == "response.output_audio.done":
            response_id = _string(payload, "response_id")
            if response_id and response_id == self._active_response and response_id not in self._retired:
                self._emit(RealtimeEvent("response_done", response_id=response_id,
                                        question_id=_string(payload, "question_id")))
                self._retire(response_id)
                self._active_response = ""
                self._waiting_for_response = False
        elif event_type in {"error", "conversation.item.input_audio_transcription.failed"}:
            # 云端错误正文可能包含用户文字；仅向本地桥暴露固定分类。
            raise RealtimeError("realtime_cloud_error")
        # usage、上下文和新增未知事件不影响本版语音链路，也不打印原始包。

    async def _read_loop(self) -> None:
        failure = None
        try:
            async for frame in self._socket:
                if not isinstance(frame, str):
                    raise RealtimeError("realtime_expected_json_frame")
                try:
                    payload = json.loads(frame)
                except (ValueError, TypeError):
                    raise RealtimeError("realtime_invalid_json") from None
                if not isinstance(payload, dict):
                    raise RealtimeError("realtime_invalid_event")
                self._handle(payload)
                if self._session_closed.is_set():
                    break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failure = str(error) if isinstance(error, RealtimeError) else "realtime_receive_failed"
        finally:
            if self._session_ready is not None and not self._session_ready.done():
                self._session_ready.set_exception(RealtimeError(failure or "realtime_session_closed"))
            if failure and not self._closing:
                # 失败时丢弃积压输出，保证桥不会先播放旧数据才看见失败状态。
                while not self._queue.empty():
                    self._queue.get_nowait()
                self._queue.put_nowait(RealtimeEvent("error", code=failure))
            if self._queue.full():
                self._queue.get_nowait()
            self._queue.put_nowait(None)

    async def receive(self) -> RealtimeEvent | None:
        return await self._queue.get()

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        while (event := await self.receive()) is not None:
            yield event

    async def close(self) -> None:
        if self._closed or self._closing:
            return
        self._closing = True
        self._listening = False
        self._audio_tail.clear()
        try:
            if self._socket is not None:
                if self._reader is not None and not self._reader.done():
                    try:
                        await self._send({"type": "session.close"}, closing=True)
                        await asyncio.wait_for(self._session_closed.wait(), self.close_timeout)
                    except (Exception, asyncio.CancelledError):
                        pass
                try:
                    await asyncio.wait_for(self._socket.close(), self.close_timeout)
                except (Exception, asyncio.CancelledError):
                    pass
        finally:
            if self._reader is not None and self._reader is not asyncio.current_task():
                self._reader.cancel()
                await asyncio.gather(self._reader, return_exceptions=True)
            if self._session_ready is not None:
                if not self._session_ready.done():
                    self._session_ready.cancel()
                elif not self._session_ready.cancelled():
                    self._session_ready.exception()
            self._closed = True
            self._closing = False
