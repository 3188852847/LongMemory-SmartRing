"""AC v1 音频事件与逐连接候选的实际桥；不读音频、不调用 ASR 或记忆接口。

AI 把已核验的完整/预识别正文与无写入 ContextSnapshot 显式送入
bind_transcript。音频版本从不充当文本版本。所有模型操作在同一事件循环；
线程到达的事件先用线程安全标记封住领取，再投递到该循环。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import math
import secrets
import threading
import weakref

from voice_preemptive import ContextSnapshot, Limits, RequestScope, TurnStamp, VoicePreemptive


STATE = "_longmemory_voice_preemptive_connection"
_SIGNALS = {"provisional": "eou", "cancel": "cancel",
            "continued": "continued_speech", "confirmed": "confirmed_turn"}


@dataclass(frozen=True)
class AudioStamp:
    turn_id: int
    audio_revision: int
    cancel_epoch: int

    def __post_init__(self):
        if any(type(x) is not int or not 0 <= x < 2**63 for x in (
                self.turn_id, self.audio_revision, self.cancel_epoch)):
            raise ValueError("preemptive_audio_stamp_invalid")


@dataclass(frozen=True)
class ASRPrefetchProof:
    """原 SenseVoice 预取已有的证明；不保存PCM或把音频版本充当文本版本。"""

    generation: int
    voice_stamp: float = field(repr=False)
    prefix_size: int
    prefix_digest: bytes = field(repr=False)
    language: str = field(repr=False)

    def __post_init__(self):
        if (type(self.generation) is not int or self.generation < 0
                or type(self.voice_stamp) not in {int, float}
                or not math.isfinite(self.voice_stamp) or self.voice_stamp <= 0
                or type(self.prefix_size) is not int or not 32000 <= self.prefix_size <= 256000
                or self.prefix_size % 1920 != 0 or not isinstance(self.prefix_digest, bytes)
                or len(self.prefix_digest) != 32 or not isinstance(self.language, str)
                or not 1 <= len(self.language) <= 64):
            raise ValueError("preemptive_asr_prefetch_proof_invalid")


@dataclass(frozen=True)
class _Event:
    kind: str
    audio: AudioStamp
    mode: str
    authoritative: bool
    reason: str

    @classmethod
    def parse(cls, event):
        if (not isinstance(event, dict) or type(event.get("version")) is not int
                or event["version"] != 1 or not isinstance(event.get("type"), str)
                or event["type"] not in _SIGNALS
                or event.get("signal") != _SIGNALS[event["type"]]
                or event.get("transcript_revision") is not None
                or event.get("mode") not in {"enabled", "shadow"}
                or type(event.get("authoritative")) is not bool
                or not isinstance(event.get("reason"), str) or len(event["reason"]) > 64
                or (event["type"] == "provisional" and event["authoritative"])
                or (event["mode"] == "shadow" and event["authoritative"])):
            raise ValueError("preemptive_ac_event_invalid")
        return cls(event["type"], AudioStamp(event.get("turn_id"), event.get("audio_revision"),
                                            event.get("cancel_epoch")),
                   event["mode"], event["authoritative"], event["reason"])


@dataclass(frozen=True, eq=False)
class TranscriptBinding:
    """只能用于创建它的连接/本代次；不包含模型答案或正式提交授权。"""

    audio: AudioStamp
    turn: TurnStamp
    _owner: object = field(repr=False)
    _generation: int = field(repr=False)
    _text: str = field(repr=False)
    _context: ContextSnapshot = field(repr=False)
    _baseline_proof: ASRPrefetchProof | None = field(default=None, repr=False)
    _model_user_message: str | None = field(default=None, repr=False)


class _Connection:
    def __init__(self, owner):
        self.owner = owner
        self.connection_id = secrets.token_hex(16)
        self.controller = VoicePreemptive(owner.model, owner.budget, limits=owner.limits)
        self.audio = self.provisional = self.confirmed = self.binding = None
        self.baseline_verified = None
        self.mode = None
        self.floor_turn = -1
        self.generation = self.text_revision = 0
        self.closed = False
        self.lock = threading.Lock()
        self.queued = 0
        self.quarantined = threading.Event()
        self.counts = dict.fromkeys(("events", "stale", "malformed", "shadow",
                                    "bound", "prepared", "missing_text", "not_confirmed",
                                    "final_mismatch", "resets", "foreign_binding"), 0)

    def quarantine(self):
        with self.lock:
            self.queued += 1
            self.quarantined.set()

    def delivered(self):
        with self.lock:
            self.queued -= 1
            if not self.queued:
                self.quarantined.clear()


class ConnectionCandidate:
    def __init__(self, manager, state, binding, lease):
        self._manager, self._state = manager, state
        self._binding, self._lease = binding, lease

    def claim(self, connection, *, binding, context, model_user_message=None):
        """AI 在正式派发门内同步领取；连接身份、音频、文本和快照仍须有效。"""
        self._manager._check_loop()
        if (self._manager._lookup(connection) is not self._state
                or binding is not self._binding
                or not self._manager._valid(self._state, binding)
                or self._state.confirmed != binding.audio):
            return None
        return self._lease.claim(turn=binding.turn, context=context, model_user_message=model_user_message)


class PreemptiveConnections:
    """实例状态挂在 connection 自身，仅计算预算及无状态模型传输可共享。"""

    def __init__(self, model, budget, *, limits=None, candidate_source="smart_turn"):
        if candidate_source not in {"smart_turn", "baseline_asr"}:
            raise ValueError("preemptive_candidate_source_invalid")
        self.model, self.budget, self.limits = model, budget, limits or Limits()
        self.candidate_source = candidate_source
        self.owner_id = secrets.token_hex(16)
        self._loop = None
        self._states = weakref.WeakSet()
        self._closed = False
        self._dropped = 0

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and loop is not self._loop:
            raise RuntimeError("preemptive_event_loop_mismatch")
        self._loop = loop

    def _lookup(self, connection):
        state = vars(connection).get(STATE)
        if state is not None and (not isinstance(state, _Connection) or state.owner is not self):
            raise RuntimeError("preemptive_connection_already_owned")
        return state

    def _state(self, connection):
        self._check_loop()
        state = self._lookup(connection)
        if state is None:
            state = _Connection(self)
            setattr(connection, STATE, state)
            self._states.add(state)
            if self._closed:
                self._close(state)
        return state

    def _dispatch(self, connection, action):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and (self._loop is None or loop is self._loop):
            self._check_loop()
            return action(self._state(connection))
        state = self._lookup(connection)
        if self._loop is None or self._loop.is_closed():
            self._dropped += 1
            if state is not None:
                state.quarantined.set()
            return False
        if state is not None:
            state.quarantine()

        def deliver():
            try:
                action(self._state(connection))
            finally:
                if state is not None:
                    state.delivered()

        try:
            self._loop.call_soon_threadsafe(deliver)
        except RuntimeError:
            self._dropped += 1
            # 循环已关闭时保留 quarantine，不能重新放行领取。
            return False
        return True

    @staticmethod
    def _order(audio):
        return audio.turn_id, audio.cancel_epoch, audio.audio_revision

    def _adopt(self, state, audio):
        if (state.closed or audio.turn_id <= state.floor_turn
                or (state.audio is not None and self._order(audio) < self._order(state.audio))):
            state.counts["stale"] += 1
            return False
        if state.audio == audio:
            return True
        previous = state.audio
        if not state.controller.begin_turn(turn_id=audio.turn_id, cancel_epoch=audio.cancel_epoch):
            state.counts["stale"] += 1
            return False
        if previous is not None and previous.turn_id == audio.turn_id:
            state.controller.context_changed()
        state.audio = audio
        state.generation += 1
        state.binding = state.provisional = state.confirmed = None
        state.baseline_verified = None
        return True

    def on_event(self, connection, event):
        """可直接交给 AC on_event；只改候选状态，绝不在回调中检索/识别。"""
        try:
            parsed = _Event.parse(event)
        except (ValueError, TypeError):
            def malformed(state):
                state.counts["malformed"] += 1
                self._invalidate(state)
                return False
            return self._dispatch(connection, malformed)
        return self._dispatch(connection, lambda state: self._event(state, parsed))

    def _event(self, state, event):
        state.counts["events"] += 1
        if self.candidate_source == "baseline_asr":
            # 两种来源的turn_id没有共同命名空间；shadow不能驱动baseline准备或确认。
            if event.mode == "shadow":
                state.counts["shadow"] += 1
            if event.kind == "cancel" and event.reason == "closed":
                self._close(state)
            return False
        if not self._adopt(state, event.audio):
            return False
        if state.mode is not None and state.mode != event.mode:
            self._invalidate(state)
        state.mode = event.mode
        if event.mode == "shadow":
            state.counts["shadow"] += 1
        if event.kind in {"cancel", "continued"}:
            self._invalidate(state)
            state.controller.cancel(turn_id=event.audio.turn_id, cancel_epoch=event.audio.cancel_epoch)
            if event.reason in {"reset", "unsupported"}:
                self._reset(state)
            elif event.reason == "closed":
                self._close(state)
        elif event.kind == "provisional":
            state.provisional = event.audio
            if state.binding is not None:
                self._prepare(state, state.binding)
            else:
                state.counts["missing_text"] += 1
        elif event.kind == "confirmed":
            # AC 仅确认音频端点；此处不确认模型候选，更不允许任何输出。
            if event.mode == "enabled" and event.authoritative:
                state.confirmed = event.audio
        return True

    def bind_transcript(self, connection, *, audio, text, context, model_user_message=None):
        """AI 传实际 ASR content 及已核验快照；晚到旧音频文本直接拒绝。"""
        if self.candidate_source != "smart_turn":
            raise ValueError("preemptive_baseline_proof_required")
        return self._bind(connection, audio=audio, text=text, context=context, model_user_message=model_user_message)

    def _bind(self, connection, *, audio, text, context, proof=None, model_user_message=None):
        if type(audio) is not AudioStamp or type(context) is not ContextSnapshot:
            raise ValueError("preemptive_binding_invalid")
        if not isinstance(text, str) or not text.strip() or len(text) > self.limits.max_input_chars:
            raise ValueError("preemptive_transcript_invalid")
        if model_user_message is not None and (not isinstance(model_user_message, str)
                or not model_user_message.strip()
                or len(model_user_message) > 16000
                or sum(len(value) for _, value in context.messages) + len(model_user_message) > 32000):
            raise ValueError("preemptive_model_user_invalid")
        state = self._state(connection)
        if state.quarantined.is_set() or not self._adopt(state, audio):
            return None
        previous = state.binding
        if (previous is not None and previous.audio == audio and previous._text == text
                and previous._context.version == context.version
                and previous._context.digest == context.digest and previous._baseline_proof == proof
                and previous._model_user_message == model_user_message):
            return previous
        text_changed = previous is None or previous._text != text or previous._model_user_message != model_user_message
        state.generation += 1
        if text_changed:
            state.text_revision += 1
        turn = TurnStamp(audio.turn_id, state.text_revision, audio.cancel_epoch)
        if previous is not None:
            state.controller.revised(turn=turn)
            if previous._context != context or previous._baseline_proof != proof:
                state.controller.context_changed()
        binding = TranscriptBinding(audio, turn, state, state.generation, text, context, proof, model_user_message)
        state.binding = binding
        state.baseline_verified = None
        state.counts["bound"] += 1
        self._prepare(state, binding)
        return binding

    @staticmethod
    def _valid(state, binding):
        return (type(binding) is TranscriptBinding and binding._owner is state
                and not state.closed and not state.quarantined.is_set()
                and state.binding is binding and state.generation == binding._generation
                and state.audio == binding.audio)

    def _prepare(self, state, binding):
        expected_mode = "baseline_asr" if self.candidate_source == "baseline_asr" else "enabled"
        if (not self._valid(state, binding) or state.mode != expected_mode
                or state.provisional != binding.audio or state.confirmed is not None):
            return False
        admitted = state.controller.provisional(turn=binding.turn, transcript=binding._text,
                                                context=binding._context,
                                                scope=RequestScope(self.owner_id, state.connection_id,
                                                                   binding.turn, binding.audio.audio_revision),
                                                model_user_message=binding._model_user_message)
        if admitted:
            state.counts["prepared"] += 1
        return admitted

    async def confirmed(self, connection, *, binding, final_text, context, model_user_message=None):
        state = self._state(connection)
        if not self._valid(state, binding):
            state.counts["foreign_binding"] += 1
            return None
        expected_mode = "baseline_asr" if self.candidate_source == "baseline_asr" else "enabled"
        if (state.mode != expected_mode or state.confirmed != binding.audio
                or (self.candidate_source == "baseline_asr" and state.baseline_verified is not binding)):
            state.counts["not_confirmed"] += 1
            return None
        if (final_text != binding._text or model_user_message != binding._model_user_message
                or type(context) is not ContextSnapshot
                or context.version != binding._context.version or context.digest != binding._context.digest):
            state.counts["final_mismatch"] += 1
            self._invalidate(state)
            return None
        lease = await state.controller.confirmed(turn=binding.turn, transcript=final_text, context=context,
                                                 model_user_message=model_user_message)
        if lease is None or not self._valid(state, binding) or state.confirmed != binding.audio:
            return None
        return ConnectionCandidate(self, state, binding, lease)

    @staticmethod
    def _invalidate(state):
        state.generation += 1
        state.binding = state.provisional = state.confirmed = None
        state.baseline_verified = None
        state.controller.context_changed()

    def context_changed(self, connection):
        return self._dispatch(connection, self._invalidate)

    def _reset(self, state, last_turn_id=None):
        self._invalidate(state)
        if state.audio is not None:
            state.floor_turn = max(state.floor_turn, state.audio.turn_id)
        elif last_turn_id is None:
            state.floor_turn += 1
        if last_turn_id is not None:
            state.floor_turn = max(state.floor_turn, last_turn_id)
        state.audio = None
        state.counts["resets"] += 1

    def reset(self, connection, *, last_turn_id=None):
        if last_turn_id is not None and (type(last_turn_id) is not int or last_turn_id < 0):
            raise ValueError("preemptive_audio_stamp_invalid")
        return self._dispatch(connection, lambda state: self._reset(state, last_turn_id))

    def _close(self, state):
        self._invalidate(state)
        state.closed = True
        state.controller.close()

    def close_connection(self, connection):
        return self._dispatch(connection, self._close)

    async def aclose_connection(self, connection, *, timeout_seconds=1.0):
        state = self._state(connection)
        self._close(state)
        return await state.controller.aclose(timeout_seconds=timeout_seconds)

    async def aclose(self, *, timeout_seconds=1.0):
        self._check_loop()
        self._closed = True
        states = tuple(self._states)
        for state in states:
            self._close(state)
        if not states:
            return self.budget.active == 0
        results = await asyncio.gather(*(state.controller.aclose(timeout_seconds=timeout_seconds)
                                         for state in states))
        return all(results) and self.budget.active == 0

    def snapshot(self, connection):
        state = self._lookup(connection)
        if state is None:
            return {"version": 1, "attached": False, "candidate_source": self.candidate_source,
                    "dropped_events": self._dropped}
        return {"version": 1, "attached": True, "closed": state.closed,
                "candidate_source": self.candidate_source,
                "quarantined": state.quarantined.is_set(), "counts": dict(state.counts),
                "candidate": state.controller.snapshot(), "dropped_events": self._dropped}

    def connection_scope(self, connection):
        """只供AI进程间控制协议使用；正式鉴权仍由宿主入口验证。"""
        state = self._state(connection)
        return self.owner_id, state.connection_id

    def baseline_asr_provisional(self, connection, *, audio, text, context, proof, model_user_message=None):
        """仅独立候选开关启用后，由原ASR预取有效结果钩子调用，不借用shadow。"""
        if self.candidate_source != "baseline_asr":
            raise ValueError("preemptive_baseline_source_not_selected")
        if type(proof) is not ASRPrefetchProof or type(audio) is not AudioStamp or proof.generation != audio.turn_id:
            raise ValueError("preemptive_asr_prefetch_proof_invalid")
        state = self._state(connection)
        if state.quarantined.is_set() or not self._adopt(state, audio):
            return None
        state.mode, state.provisional = "baseline_asr", audio
        return self._bind(connection, audio=audio, text=text, context=context, proof=proof,
                          model_user_message=model_user_message)

    def baseline_continued(self, connection, *, audio):
        if self.candidate_source != "baseline_asr" or type(audio) is not AudioStamp:
            raise ValueError("preemptive_baseline_source_not_selected")

        def continued(state):
            if self._adopt(state, audio):
                self._invalidate(state)

        return self._dispatch(connection, continued)

    async def baseline_confirmed(self, connection, *, binding, final_text, context,
                                 final_pcm, generation, voice_stamp, language, model_user_message=None):
        """仅原端点+完整正式ASR之后调用；原始音频只用于有界前缀核验，不保留。"""
        if self.candidate_source != "baseline_asr":
            raise ValueError("preemptive_baseline_source_not_selected")
        state = self._state(connection)
        if not self._valid(state, binding):
            state.counts["foreign_binding"] += 1
            return None
        proof = binding._baseline_proof
        matches = (proof is not None and type(generation) is int and generation == proof.generation
                   and type(voice_stamp) in {float, int} and voice_stamp == proof.voice_stamp
                   and language == proof.language and isinstance(final_pcm, bytes)
                   and len(final_pcm) >= proof.prefix_size
                   and hashlib.sha256(final_pcm[:proof.prefix_size]).digest() == proof.prefix_digest)
        del final_pcm  # 等待模型或RPC时不额外持有原音频引用。
        if not matches:
            state.counts["final_mismatch"] += 1
            self._invalidate(state)
            return None
        state.confirmed, state.baseline_verified = binding.audio, binding
        return await self.confirmed(connection, binding=binding, final_text=final_text, context=context,
                                    model_user_message=model_user_message)


def install_preemptive_connection_lifecycle(connection_class, bridge):
    """AI 显式接线：reset 一律撤销，close 保证异常路径也撤销，不碰 launch。"""
    if getattr(connection_class, "_longmemory_preemptive_lifecycle_installed", False):
        raise RuntimeError("preemptive_lifecycle_already_installed")
    reset, close = connection_class.reset_audio_states, connection_class.close

    def reset_audio_states(connection, *args, **kwargs):
        snapshot = getattr(connection, "_longmemory_voice_turn_end_snapshot", None)
        last_turn_id = None
        if bridge.candidate_source == "smart_turn" and callable(snapshot):
            try:
                candidate = snapshot().get("turn_id")
                if type(candidate) is int and candidate >= 0:
                    last_turn_id = candidate
            except Exception:
                pass  # 只有版本元数据；读取失败仍撤销，不影响原reset。
        bridge.reset(connection, last_turn_id=last_turn_id)
        return reset(connection, *args, **kwargs)

    async def close_connection(connection, *args, **kwargs):
        bridge.close_connection(connection)
        try:
            return await close(connection, *args, **kwargs)
        finally:
            await bridge.aclose_connection(connection)

    connection_class.reset_audio_states = reset_audio_states
    connection_class.close = close_connection
    connection_class._longmemory_preemptive_lifecycle_installed = True
