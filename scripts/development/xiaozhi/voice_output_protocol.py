"""直接WebSocket的显式TTS撤权屏障；不改变二进制头或运行模型。

必须在进程内撤权/发送包装之后安装；代理是该连接交给上游的唯一socket。
普通stop保留EOS；只有本地撤权来源才生成interrupt，不把发送返回当设备静音回执。
"""

import asyncio
from collections import Counter, deque
import copy
from contextlib import contextmanager
from contextvars import ContextVar
import json
import threading

import voice_interruption as guard

CAPABILITY = "tts_interrupt_v1"
MAX_EPOCH = 2147483647
ATTRIBUTE = "_longmemory_tts_interrupt_wire"
_OWNER = ContextVar("tts_wire_owner", default=None)
_INPUT = ContextVar("tts_wire_input", default=None)
_ABORT = ContextVar("tts_wire_abort", default=None)
COUNTERS = ("hello_confirmed", "start_sent", "audio_sent", "subtitle_sent", "eos_sent",
            "interrupt_sent", "stale_dropped", "unowned_dropped", "send_timeout", "closed")


class StaleOutput(Exception):
    """没有真实写出；上游不得把它计为已发送帧。"""


class OutputUnavailable(ConnectionError):
    pass


class Turn:
    def __init__(self, protocol, epoch):
        self.protocol, self.epoch = protocol, epoch
        self.revoked = self.eos = self.started = False

    def current(self):
        return self.identity_current() and not self.eos

    def identity_current(self):
        p = self.protocol
        return not p.closed and p.turn is self and not self.revoked


class Owner:
    def __init__(self, protocol, turn, lease=None):
        self.protocol, self.turn, self.lease = protocol, turn, lease
        self.revocation = guard.state_for(protocol.connection).epoch
        self.input = _INPUT.get()

    def current(self):
        p = self.protocol
        return (not p.closed and guard.state_for(p.connection).epoch == self.revocation
                and (self.lease is None or self.lease.current())
                and (self.input is None or self.input == (p, p.input_generation))
                and (self.turn is None or self.turn.current()))


def protocol_snapshot(connection=None):
    p = getattr(connection, ATTRIBUTE, None)
    if p is None:
        return {"version": 1, "state": "not_installed" if connection is not None else "no_connection",
                "negotiated": False, "device_playback_acknowledged": False,
                "counts": {name: 0 for name in COUNTERS}, "active_writes": 0,
                "reason": "not_installed" if connection is not None else "no_connection"}
    return p.snapshot()


class OutputProtocol:
    def __init__(self, connection, raw, *, send_timeout=2.0):
        if type(send_timeout) not in {int, float} or not 0 < send_timeout <= 5:
            raise ValueError("invalid_tts_send_timeout")
        self.connection, self.raw, self.send_timeout = connection, raw, send_timeout
        self.gate = asyncio.Lock()
        self.state_lock = threading.RLock()
        self.negotiated = self.closed = self.hello_sent = False
        self.client_capability = False
        self.reason = "hello_pending"
        self.turn = None
        self.next_epoch = self.input_generation = 0
        self.pending = deque()
        self.counts = Counter()
        self.writes = set()
        self.close_task = None

    def snapshot(self):
        with self.state_lock:
            return {"version": 1, "state": "closed" if self.closed else (
                        "negotiated" if self.negotiated else ("legacy" if self.hello_sent else "hello_pending")),
                    "negotiated": self.negotiated, "reason": self.reason,
                    "counts": {name: self.counts.get(name, 0) for name in COUNTERS},
                    "active_writes": len(self.writes), "device_playback_acknowledged": False}

    def eligible(self):
        c = self.connection
        coverage = getattr(type(c), "_longmemory_tts_wire_coverage", None)
        config = getattr(c, "config", {})
        selected = config.get("selected_module") if isinstance(config, dict) else None
        engines = config.get("TTS") if isinstance(config, dict) else None
        custom = engines.get("CustomTTS") if isinstance(engines, dict) else None
        local_cosy = (isinstance(selected, dict) and selected.get("TTS") == "CustomTTS"
                      and isinstance(custom, dict)
                      and custom.get("url") == "http://127.0.0.1:18770/v1/audio/speech")
        return (getattr(type(c), "_longmemory_tts_wire_installed", False) is True
                and callable(coverage) and coverage()
                and getattr(type(c), "_longmemory_audio_revocation_installed", False) is True
                and getattr(c, "websocket", None) is self.proxy
                and not getattr(c, "conn_from_mqtt_gateway", False)
                and getattr(c, "_doubao_bridge", None) is None
                and getattr(c, "voice_mode", "pipeline") == "pipeline" and local_cosy)

    def observe_incoming(self, message):
        if self.hello_sent or not isinstance(message, str) or len(message) > 65536:
            return
        try:
            item = json.loads(message)
        except (ValueError, TypeError):
            return
        if isinstance(item, dict) and item.get("type") == "hello":
            features = item.get("features")
            self.client_capability = isinstance(features, dict) and features.get(CAPABILITY) is True

    @contextmanager
    def input_scope(self):
        # 正式输入中的长意图await也不能让更早输入的start在新输入后复活。
        with self.state_lock:
            self.input_generation += 1
            token = _INPUT.set((self, self.input_generation))
        try:
            yield
        finally:
            _INPUT.reset(token)

    def capture_turn(self):
        with self.state_lock:
            return self.turn

    def current_lease(self):
        owner = _OWNER.get()
        return owner.lease if owner is not None and owner.protocol is self else None

    @staticmethod
    def is_stale_error(error):
        return isinstance(error, StaleOutput)

    def revoke(self, reason):
        with self.state_lock:
            turn = self.turn
            # EOS只关闭接收；没有播放回执，设备可能仍在排空该轮尾音。
            if turn is not None and not turn.revoked:
                turn.revoked = True
                if turn.started and self.negotiated:
                    self.pending.append(turn)
            # 捕获此次abort的目标；迟到raw stop不得误指向下一轮。
            _ABORT.set((self, turn))

    def has_interrupt_target(self):
        with self.state_lock:
            return (self.negotiated and not self.closed and self.turn is not None
                    and self.turn.started and not self.turn.revoked)

    def _reserve(self):
        if self.next_epoch >= MAX_EPOCH:
            self._invalidate("epoch_exhausted")
            if self.close_task is None:
                self.close_task = asyncio.create_task(self._close_raw())
            raise OutputUnavailable("tts_epoch_exhausted")
        previous = self.turn
        if previous is not None and previous.current():
            previous.revoked = True
            if previous.started:
                self.pending.append(previous)
        self.next_epoch += 1
        self.turn = Turn(self, self.next_epoch)
        return self.turn

    @contextmanager
    def scope(self, lease=None, *, kind="message"):
        prior = _OWNER.get()
        if prior is not None and prior.protocol is self:
            yield
            return
        valid = lease is not None and lease.current()
        with self.state_lock:
            turn = None if kind == "start" else (getattr(lease, "wire_turn", None) if lease is not None else self.turn)
            if (self.negotiated and kind in {"message", "packet"} and turn is None
                    and valid):
                turn = self._reserve()  # 无显式start的绑定/公告路径也先补一条start。
                lease.wire_turn = turn
            owner = Owner(self, turn, lease)
            token = _OWNER.set(owner)
        try:
            yield
        finally:
            _OWNER.reset(token)

    def _invalidate(self, reason):
        with self.state_lock:
            if not self.closed:
                self.counts["closed"] += 1
                self.reason = reason
            self.closed = True
            if self.turn is not None:
                self.turn.revoked = True
            self.pending.clear()

    async def _close_raw(self, code=1011):
        # 只关闭本连接；握手/发送超时不能留下仍能写的socket后再报告flush成功。
        try:
            await asyncio.wait_for(self.raw.close(code=code, reason="tts_output_closed"), .5)
        except (Exception, asyncio.CancelledError):
            pass
        transport = getattr(self.raw, "transport", None)
        if transport is not None and not transport.is_closing():
            transport.abort()

    async def _fail(self, reason, *, close_code=1011):
        self._invalidate(reason)
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close_raw(close_code))
        await asyncio.shield(self.close_task)
        for task in tuple(self.writes):
            task.cancel()
        if self.writes:
            await asyncio.wait(tuple(self.writes), timeout=.25)

    async def close(self, *args, **kwargs):
        state = guard.state_for(self.connection)
        with state.lock:
            state.closed = True
        await self._fail("connection_closed", close_code=kwargs.get("code", args[0] if args else 1000))

    async def _write(self, value):
        if self.closed:
            raise OutputUnavailable("tts_output_closed")
        task = asyncio.create_task(self.raw.send(value))
        self.writes.add(task)
        def finished(done):
            self.writes.discard(done)
            if not done.cancelled():
                done.exception()  # 连接已关闭的收尾也要消费异常，不产生未回收任务告警。
        task.add_done_callback(finished)
        # caller取消（原生rate.reset）不能让尚在await的旧写出越过interrupt。
        cancelled = False
        try:
            try:
                done, _ = await asyncio.wait({task}, timeout=self.send_timeout)
            except asyncio.CancelledError:
                cancelled = True
                done, _ = await asyncio.wait({task}, timeout=self.send_timeout)
            if not done:
                self.counts["send_timeout"] += 1
                await self._fail("send_timeout")
                raise OutputUnavailable("tts_send_timeout")
            result = task.result()
            if cancelled:
                raise asyncio.CancelledError()
            return result
        except asyncio.CancelledError:
            if not task.done():
                await self._fail("cancelled_write_unsettled")
            raise
        except Exception:
            if not self.closed:
                await self._fail("send_failed")
            raise

    def _tts(self, state, turn):
        return {"type": "tts", "state": state, "session_id": self.connection.session_id,
                "output_epoch": turn.epoch}

    async def _interrupts(self):
        while self.pending:
            turn = self.pending.popleft()
            await self._write(json.dumps(self._tts("interrupt", turn)))
            self.counts["interrupt_sent"] += 1

    async def _start(self, turn):
        if not turn.started:
            # 在await前登记；并发abort必须将正在写出的start也列入interrupt屏障。
            turn.started = True
            await self._write(json.dumps(self._tts("start", turn)))
            self.counts["start_sent"] += 1

    async def send(self, value):
        item = None
        if isinstance(value, str):
            try:
                candidate = json.loads(value)
                item = candidate if isinstance(candidate, dict) else None
            except ValueError:
                pass
        hello = item is not None and item.get("type") == "hello"
        tts = item is not None and item.get("type") == "tts"
        binary = isinstance(value, (bytes, bytearray, memoryview))
        is_start = tts and item.get("state") == "start"
        abort = _ABORT.get()
        abort_stop = tts and item.get("state") == "stop" and abort is not None and abort[0] is self
        if abort_stop:
            _ABORT.set(None)
        owner = _OWNER.get()
        if owner is None or owner.protocol is not self:
            lease = guard.current_output_lease(self.connection)
            owner = Owner(self, None if is_start else (
                getattr(lease, "wire_turn", None) if lease is not None else self.turn), None if is_start else lease)
        # 在等待gate前固定来源；绝不能进门后改用“现在的新轮”。
        if self.negotiated and is_start and owner.current():
            with self.state_lock:
                owner.turn = self._reserve()
        acquire = asyncio.create_task(self.gate.acquire())
        try:
            done, _ = await asyncio.wait({acquire}, timeout=self.send_timeout)
        except asyncio.CancelledError:
            acquire.cancel()
            await asyncio.gather(acquire, return_exceptions=True)
            if not acquire.cancelled() and acquire.result():
                self.gate.release()
            raise
        if not done:
            acquire.cancel()
            await asyncio.gather(acquire, return_exceptions=True)
            if not acquire.cancelled() and acquire.result():
                self.gate.release()
            self.counts["send_timeout"] += 1
            await self._fail("gate_timeout")
            raise OutputUnavailable("tts_gate_timeout") from None
        try:
            if self.closed:
                raise OutputUnavailable("tts_output_closed")
            if hello:
                copy = dict(item)
                features = dict(copy.get("features")) if isinstance(copy.get("features"), dict) else {}
                features.pop(CAPABILITY, None)
                first = not self.hello_sent
                confirmed = self.client_capability and self.eligible() if first else self.negotiated
                if confirmed:
                    features[CAPABILITY] = True
                copy["features"] = features
                await self._write(json.dumps(copy))
                if first:
                    self.negotiated = confirmed
                    self.reason = "confirmed" if confirmed else "legacy_not_confirmed"
                    self.hello_sent = True
                if self.negotiated:
                    self.counts["hello_confirmed"] += 1
                return None
            if not self.negotiated:
                return await self._write(value)
            if not self.eligible():
                await self._fail("mode_changed")
                raise OutputUnavailable("tts_mode_changed")
            if not isinstance(value, (str, bytes, bytearray, memoryview)):
                self.counts["unowned_dropped"] += 1
                raise StaleOutput()  # 拒绝可绕过音频归属检查的fragment iterable。
            await self._interrupts()
            if abort_stop:
                return None  # 目标可能早已由下一轮发送代为flush，不再发普通stop。
            if (item is not None and item.get("type") in {"stt", "tts"}
                    and owner.input is not None and owner.input != (self, self.input_generation)):
                self.counts["stale_dropped"] += 1
                raise StaleOutput()
            if binary or tts:
                if not owner.current():
                    self.counts["stale_dropped"] += 1
                    raise StaleOutput()
                if binary and (_OWNER.get() is None or owner.lease is None):
                    self.counts["unowned_dropped"] += 1
                    raise StaleOutput()
                turn = owner.turn
                if turn is None or not turn.current():
                    self.counts["unowned_dropped"] += 1
                    raise StaleOutput()
                state = item.get("state") if tts else None
                if tts and state not in {"start", "sentence_start", "stop"}:
                    self.counts["unowned_dropped"] += 1
                    raise StaleOutput()
                await self._start(turn)
                if is_start:
                    return None
                if not owner.current():
                    # 自动补start本身也会await；其间撤权后不得再开始写此轮音频/字幕。
                    self.counts["stale_dropped"] += 1
                    raise StaleOutput()
                if binary:
                    await self._write(value)
                    self.counts["audio_sent"] += 1
                else:
                    copy = dict(item)
                    copy["output_epoch"] = turn.epoch
                    await self._write(json.dumps(copy))
                    self.counts["eos_sent" if state == "stop" else "subtitle_sent"] += 1
                    if state == "stop":
                        turn.eos = True
                return None
            return await self._write(value)
        finally:
            self.gate.release()


class SocketProxy:
    def __init__(self, protocol):
        self.protocol = protocol

    def __getattr__(self, name):
        return getattr(self.protocol.raw, name)

    async def __aiter__(self):
        async for value in self.protocol.raw:
            self.protocol.observe_incoming(value)
            yield value

    async def send(self, value):
        return await self.protocol.send(value)

    async def close(self, *args, **kwargs):
        return await self.protocol.close(*args, **kwargs)


def install_tts_interrupt_protocol(connection_class, send_module, *, hello_module, listen_module,
                                   upstream_root, send_timeout=2.0):
    """在既有guard/voice/waiting包装之后安装；所有参数是已经加载的固定上游模块。"""
    if getattr(connection_class, "_longmemory_tts_wire_installed", False):
        return {"version": 1, "installed": True}
    if not getattr(connection_class, "_longmemory_audio_revocation_installed", False):
        raise ValueError("tts_revocation_required")
    from control_compatibility import verify_control_snapshot
    verify_control_snapshot(upstream_root)
    original_handle = connection_class.handle_connection
    async def handle(connection, raw):
        # 固定上游会给config[xiaozhi]写session_id/hello音频参数，先隔离本连接副本。
        connection.config = dict(connection.config)
        connection.config["xiaozhi"] = copy.deepcopy(connection.config.get("xiaozhi", {}))
        p = OutputProtocol(connection, raw, send_timeout=send_timeout)
        p.proxy = SocketProxy(p)
        setattr(connection, ATTRIBUTE, p)
        try:
            return await original_handle(connection, p.proxy)
        finally:
            await p.close()
    connection_class.handle_connection = handle
    connection_class._longmemory_tts_interrupt_snapshot = protocol_snapshot

    original_packet = send_module._do_send_audio
    async def packet(connection, value, flow):
        p = getattr(connection, ATTRIBUTE, None)
        if p is None or not p.negotiated:
            return await original_packet(connection, value, flow)
        lease = (guard.current_output_lease(connection) or getattr(value, "_longmemory_output_lease", None)
                 or guard.OutputLease(connection, flow.get("sentence_id")))
        try:
            with p.scope(lease, kind="packet"):
                return await original_packet(connection, value, flow)
        except StaleOutput:
            return None
    send_module._do_send_audio = packet

    def message(original):
        async def wrapped(connection, *args, **kwargs):
            p = getattr(connection, ATTRIBUTE, None)
            if p is None or not p.negotiated:
                return await original(connection, *args, **kwargs)
            sentence = kwargs.get("sentence_id", args[3] if len(args) > 3 else getattr(connection, "sentence_id", None))
            lease = guard.current_output_lease(connection) or guard.OutputLease(connection, sentence)
            try:
                with p.scope(lease):
                    return await original(connection, *args, **kwargs)
            except (StaleOutput, guard._StaleControl):
                return None
        return wrapped

    def control(original):
        async def wrapped(connection, state, text=None):
            p = getattr(connection, ATTRIBUTE, None)
            if p is None or not p.negotiated:
                return await original(connection, state, text)
            # start发生在新sentence UUID创建前，不能绑定仍被撤销的旧UUID。
            lease = None if state == "start" else (guard.current_output_lease(connection)
                or guard.OutputLease(connection, getattr(connection, "sentence_id", None)))
            try:
                with p.scope(lease, kind="start" if state == "start" else "control"):
                    return await original(connection, state, text)
            except (StaleOutput, guard._StaleControl):
                return None
        return wrapped
    # 已导入别名保留各自已有包装；其最终socket仍统一经过proxy。
    hello_message = hello_module.sendAudioMessage = message(hello_module.sendAudioMessage)
    hello_control = hello_module.send_tts_message = control(hello_module.send_tts_message)
    listen_control = listen_module.send_tts_message = control(listen_module.send_tts_message)
    send_control = send_module.send_tts_message = control(send_module.send_tts_message)
    def coverage():
        return (send_module._do_send_audio is packet and send_module.send_tts_message is send_control
                and hello_module.sendAudioMessage is hello_message
                and hello_module.send_tts_message is hello_control
                and listen_module.send_tts_message is listen_control)
    connection_class._longmemory_tts_wire_coverage = staticmethod(coverage)
    connection_class._longmemory_tts_wire_installed = True
    return {"version": 1, "installed": True}
