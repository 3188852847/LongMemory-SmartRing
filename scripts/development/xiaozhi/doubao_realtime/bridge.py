"""实时语音与圆屏协议之间的会话桥；不导入记忆核心、不保存音频或转写。

云客户端负责供应商协议，这里只消费统一事件。输入、输出各有一个有界
队列；打断时替换输出队列并取消旧消费者，避免新话轮清除 abort 标志后
旧音频重新进入扬声器。所有对象归属当前连接的 asyncio 事件循环。
"""

import asyncio
import json
import time
from uuid import uuid4


class RealtimeBridge:
    def __init__(self, connection, client, encoder, *, audio_sender, state_sender,
                 queue_limit=128):
        self.connection = connection
        self.client = client
        self.encoder = encoder
        self.audio_sender = audio_sender
        self.state_sender = state_sender
        self.queue_limit = queue_limit
        self.input_queue = asyncio.Queue(maxsize=queue_limit)
        self.output_queue = asyncio.Queue(maxsize=queue_limit)
        self.generation = 0
        self.response_id = None
        self.retired_responses = set()
        self._retired_order = []
        self._response_ended = False
        self._accept_response = True
        self._queued_audio_bytes = 0
        self._failure_pending = False
        self._tasks = set()
        self._output_task = None
        self._closed = False
        self._close_complete = asyncio.Event()
        self._closing_task = None
        self.ready = False
        self.listening = False
        self.failure_code = None
        self._interrupt_lock = asyncio.Lock()

    def snapshot(self):
        """诊断仅返回状态，不回传云端文本、音频、ID、密钥或异常正文。"""
        return {
            "ready": self.ready and not self._closed,
            "listening": self.listening,
            "responding": bool(self.connection.client_is_speaking),
            "memory_enabled": False,
            "announcement_supported": False,
            "failure_code": self.failure_code,
        }

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def start(self):
        await self.client.connect()
        if self._closed:
            await self.client.close()
            return
        self.ready = True
        self._output_task = self._spawn(self._output_loop(self.output_queue))
        self._spawn(self._input_loop())
        self._spawn(self._receive_loop())

    def _retire(self, response_id):
        if response_id and response_id not in self.retired_responses:
            self.retired_responses.add(response_id)
            self._retired_order.append(response_id)
            # 单连接有限历史；正常一分钟只会有少量话轮。
            if len(self._retired_order) > 256:
                self.retired_responses.discard(self._retired_order.pop(0))

    async def accept_pcm(self, pcm):
        if not self.ready or self._closed or not self.listening:
            return
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2:
            return
        await self._enqueue_input("audio", pcm)

    async def _enqueue_input(self, kind, payload=None):
        try:
            self.input_queue.put_nowait((kind, payload))
        except asyncio.QueueFull:
            await self._fail("realtime_input_overflow")

    async def listen(self, state, mode=None, text=None):
        if mode in {"auto", "manual", "realtime"}:
            self.connection.client_listen_mode = mode
        if not self.ready or self._closed:
            return
        if state == "start":
            self.connection.reset_audio_states()
            self.listening = True
            await self._enqueue_input("start")
        elif state == "stop":
            # 把结束动作排在PCM后，让设备路由立即返回并继续处理abort。
            # 同一上传消费者保证最后一包→commit→mute→下次start的顺序。
            self.listening = False
            await self._enqueue_input("stop")
        elif state == "detect":
            # 圆屏唤醒文本不是用户完整输入，不套用旧 ChatTextQuery 协议，
            # 也不自动归档或让模型虚构回答。唤醒后直接进入云端监听。
            self.connection.reset_audio_states()
            self.listening = True
            await self._enqueue_input("start")

    async def _input_loop(self):
        try:
            while not self._closed:
                kind, payload = await self.input_queue.get()
                try:
                    if kind == "audio":
                        await asyncio.wait_for(self.client.send_audio(payload), timeout=5)
                    elif kind == "start":
                        await asyncio.wait_for(self.client.start_listening(), timeout=5)
                    elif kind == "stop":
                        await asyncio.wait_for(self.client.commit(), timeout=5)
                        await asyncio.wait_for(self.client.stop_listening(), timeout=5)
                finally:
                    self.input_queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._fail("realtime_upload_failed")

    async def _receive_loop(self):
        try:
            async for event in self.client.events():
                if self._closed:
                    break
                await self.handle_event(event)
                if self._closed:
                    break
            if not self._closed:
                await self._fail("realtime_cloud_closed")
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._fail("realtime_receive_failed")

    async def handle_event(self, event):
        """只处理客户端规范化事件；partial 不调用记忆、不当作最终用户事实。"""
        if self._closed:
            return
        value = (lambda name, default="": event.get(name, default)) if isinstance(event, dict) else (
            lambda name, default="": getattr(event, name, default))
        kind = value("kind")
        rid = value("response_id")
        if kind == "speech_started":
            self.connection.last_activity_time = time.time() * 1000
            self.connection.client_have_voice = True
            # 云端已检测到新用户说话；本地立即停声，不等待另一轮云取消应答。
            await self.interrupt(notify_cloud=False)
            self._accept_response = True
        elif kind == "transcript":
            if value("is_final", False):
                self.connection.client_have_voice = False
                self.connection.last_activity_time = time.time() * 1000
            if value("is_final", False) and value("text"):
                await self.connection.websocket.send(json.dumps({
                    "type": "stt", "text": value("text"),
                    "session_id": self.connection.session_id,
                }, ensure_ascii=False))
        elif kind == "response_started":
            if (not self._accept_response or not rid or rid in self.retired_responses
                    or rid == self.response_id):
                return
            if self.response_id is not None and not self._response_ended:
                await self._fail("realtime_response_sequence_invalid")
                return
            # 正常下一段回答排在上一段end后；不能按“打断”清掉仍在设备
            # 发送队列里的尾音。只有speech_started/显式abort改变generation。
            self.response_id = rid
            self._response_ended = False
            self.connection.client_abort = False
            self._enqueue("start", None)
        elif kind in {"audio", "text", "response_done"}:
            if (not rid or rid != self.response_id or rid in self.retired_responses
                    or self._response_ended):
                return
            if kind == "response_done":
                self._response_ended = True
                self._enqueue("end", None)
            elif kind == "audio":
                pcm = value("audio", b"")
                if not isinstance(pcm, bytes) or len(pcm) % 2:
                    await self._fail("realtime_audio_invalid")
                elif pcm:
                    self._enqueue("audio", pcm)
            elif value("text"):
                self._enqueue("text", value("text"))
        elif kind == "canceled":
            if rid and rid == self.response_id:
                await self.interrupt(notify_cloud=False)
        elif kind == "error":
            code = "realtime_turn_ambiguous" if value("code") == "realtime_turn_ambiguous" else "realtime_cloud_error"
            await self._fail(code)

    def _enqueue(self, kind, payload):
        try:
            if self._failure_pending:
                return
            if kind == "audio" and self._queued_audio_bytes + len(payload) > 240000:
                raise asyncio.QueueFull
            self.output_queue.put_nowait((self.generation, self.response_id, kind, payload))
            if kind == "audio":
                self._queued_audio_bytes += len(payload)
        except asyncio.QueueFull:
            # 不静默丢掉中间音频；关闭当前会话，让用户看到明确的不可用状态。
            if not self._failure_pending:
                self._failure_pending = True
                self._spawn(self._fail("realtime_output_overflow"))

    async def _output_loop(self, owned_queue):
        try:
            while not self._closed:
                generation, rid, kind, payload = await owned_queue.get()
                try:
                    if generation != self.generation:
                        continue
                    if kind == "audio":
                        self._queued_audio_bytes -= len(payload)
                    if kind == "start":
                        self.connection.sentence_id = uuid4().hex
                        self.encoder.reset_state()
                        self.connection.client_is_speaking = True
                        await self.state_sender(self.connection, "start")
                    elif kind == "text":
                        await self.state_sender(self.connection, "sentence_start", payload)
                    elif kind in {"audio", "end"}:
                        packets = []
                        self.encoder.encode_pcm_to_opus_stream(
                            payload if kind == "audio" else b"", kind == "end", packets.append)
                        for packet in packets:
                            if generation != self.generation:
                                break
                            # 沿用上游60ms节拍器与direct_ws_v2封装/AEC参考缓存。
                            await self._send_packet(packet, generation)
                        if kind == "end" and generation == self.generation:
                            await self.state_sender(self.connection, "stop")
                            if generation == self.generation:
                                self.connection.client_is_speaking = False
                                self._retire(rid)
                                if rid == self.response_id:
                                    self.response_id = None
                finally:
                    owned_queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._fail("realtime_playback_failed")

    async def _send_packet(self, packet, generation):
        # 上游sendAudio只向自己的deque入队，因此桥队列有界还不够。
        # 限制节拍队列最多约1.9秒库存，把背压留在当前消费者，避免云端
        # 快速生成长回答后出现另一层无界积压。整个等待可被打断取消。
        deadline = asyncio.get_running_loop().time() + 5
        while generation == self.generation:
            controller = getattr(self.connection, "audio_rate_controller", None)
            if controller is None or len(controller.queue) < 32:
                await self.audio_sender(self.connection, packet)
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("realtime_playback_stalled")
            await asyncio.sleep(0.02)

    def reset_output(self):
        """即时失效旧话轮；也供上游同步 clear_queues 调用。"""
        self.generation += 1
        self._retire(self.response_id)
        self.response_id = None
        self._response_ended = False
        self._accept_response = False
        self.connection.sentence_id = uuid4().hex
        self.connection.client_abort = True
        controller = getattr(self.connection, "audio_rate_controller", None)
        if controller is not None:
            controller.reset()
        if self._output_task is not None and self._output_task is not asyncio.current_task():
            self._output_task.cancel()
        self.output_queue = asyncio.Queue(maxsize=self.queue_limit)
        self._queued_audio_bytes = 0
        if self.ready and not self._closed:
            self._output_task = self._spawn(self._output_loop(self.output_queue))
        self.connection.client_is_speaking = False

    async def interrupt(self, *, notify_cloud=True):
        failed = False
        async with self._interrupt_lock:
            active = self.response_id is not None or self.connection.client_is_speaking
            self.reset_output()
            if active:
                # 中止不能等待残余包播放完；直接stop并已清空节拍队列。
                await self.connection.websocket.send(json.dumps({
                    "type": "tts", "state": "stop",
                    "session_id": self.connection.session_id,
                }))
            if notify_cloud and self.ready and not self._closed:
                try:
                    await asyncio.wait_for(self.client.interrupt(), timeout=5)
                except Exception:
                    failed = True
        if failed:
            await self._fail("realtime_cancel_failed")

    async def _fail(self, code):
        if self._closed:
            return
        self.failure_code = code
        try:
            await self.interrupt(notify_cloud=False)
        finally:
            try:
                await self.close()
            finally:
                # 留着设备WS会使后续listen/audio被静默丢弃。结束设备连接
                # 让终端重新握手；不在原会话内自动重放音频或重试有费用请求。
                try:
                    await asyncio.wait_for(self.connection.websocket.close(), timeout=3)
                except Exception:
                    pass

    async def close(self):
        if self._closed:
            if asyncio.current_task() is not self._closing_task:
                await self._close_complete.wait()
                if self._closing_task in self._tasks:
                    await asyncio.gather(self._closing_task, return_exceptions=True)
            return
        self._closing_task = asyncio.current_task()
        self._closed = True
        self.ready = False
        self.listening = False
        self.reset_output()
        # join等待者必须释放；关闭状态下不再上传任何排队音频。
        while not self.input_queue.empty():
            self.input_queue.get_nowait()
            self.input_queue.task_done()
        current = asyncio.current_task()
        pending = [task for task in self._tasks if task is not current]
        for task in pending:
            task.cancel()
        try:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            try:
                await asyncio.wait_for(self.client.close(), timeout=5)
            except Exception:
                self.failure_code = self.failure_code or "realtime_close_failed"
        finally:
            try:
                self.encoder.close()
            finally:
                self._close_complete.set()
