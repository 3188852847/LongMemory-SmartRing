"""宿主候选编排：只读快照、冻结消息、fresh临界区领取；不作正式副作用。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ThreadTimeout
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import secrets
import sys
from threading import Lock
from time import monotonic
from uuid import UUID

from longmemory.methods.hy_memory.provider_transport import finish_before_cancel


SNAPSHOT_TTL = 10.0
MAX_CONNECTIONS = 16
MAX_OPERATIONS = 200
RUNTIME_TIMEOUT = 1.0
CLAIM_TIMEOUT = .25
CLOSE_TIMEOUT = .5
MAX_SNAPSHOT_BYTES = 192*1024
MAX_CONTEXT_BYTES = 64*1024
COMMON = {'version', 'connection_id', 'turn_id', 'transcript_revision', 'cancel_epoch'}


@lru_cache(maxsize=1)
def _load_controllers():
    """加载本检出的AE实现，缺少时拒绝，不在3.10语音进程复制宿主或模型。"""
    root = Path(__file__).resolve().parents[3]/'scripts/development/xiaozhi'
    modules = []
    for file in ('voice_preemptive.py', 'voice_preemptive_stream.py'):
        name = '_longmemory_host_'+file[:-3]
        path = root/file
        if not path.is_file():
            raise RuntimeError('voice_proposal_controller_unavailable')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    if not hasattr(modules[0], 'RequestScope'):
        raise RuntimeError('voice_proposal_close_confirmation_required')
    return tuple(modules)


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _scope(body, required=(), optional=()):
    if (not isinstance(body, dict) or not COMMON | set(required) <= set(body)
            or not set(body) <= COMMON | set(required) | set(optional)
            or type(body.get('version')) is not int or body['version'] != 1
            or not isinstance(body.get('connection_id'), str) or re.fullmatch(r'[0-9a-f]{32}', body['connection_id']) is None
            or any(type(body.get(key)) is not int or not 0 <= body[key] < 2**63
                   for key in ('turn_id', 'transcript_revision', 'cancel_epoch'))):
        raise ValueError('voice_proposal_request_invalid')
    return (body['turn_id'], body['transcript_revision'], body['cancel_epoch'])


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise ValueError('voice_proposal_request_invalid')
    return value


def _session(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{32}', value) is None:
        raise ValueError('voice_proposal_request_invalid')
    return value


def _messages(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 128
            or any(not isinstance(row, list) or len(row) != 2
                   or not isinstance(row[0], str) or row[0] not in {'system', 'user', 'assistant'}
                   or not isinstance(row[1], str) for row in value)
            or value[0][0] != 'system' or any(row[0] == 'system' for row in value[1:])
            or sum(len(row[1]) for row in value) > 32000):
        raise ValueError('voice_proposal_request_invalid')
    return tuple((row[0], row[1]) for row in value)


def _miss(kind, reason='unavailable'):
    result = {'version': 1, 'state': 'unavailable' if kind == 'snapshot' else 'miss', 'reason_code': reason}
    if kind == 'snapshot': result.update(snapshot_id=None, memory_context=None)
    if kind == 'confirm': result['text'] = None
    return result


def _cancel_result(done, *, closing):
    return {'version': 1, 'state': ('closed' if closing else 'cancelled') if done else 'closing',
            'owned_upstream_exited': done, 'provider_compute_stopped': False}


@dataclass(eq=False)
class _Connection:
    stamp: tuple
    generation: int = 0
    closed: bool = False
    controller: object = field(default=None, repr=False)
    retired: list = field(default_factory=list, repr=False)
    attempted_turn: int = -1


@dataclass(eq=False)
class _Snapshot:
    connection_id: str
    stamp: tuple
    generation: int
    query: str = field(repr=False)
    session_id: str | None = field(repr=False)
    receipt: dict = field(repr=False)
    runtime: object = field(repr=False)
    context_text: str = field(repr=False)
    expires: float
    messages: tuple | None = field(default=None, repr=False)
    context: object = field(default=None, repr=False)
    policy_revision: str | None = field(default=None, repr=False)
    consumed: bool = False


class _ClaimGate:
    """Runtime锁内的worker只能同步等loop领取；撤销与领取用同一原子门。"""

    def __init__(self, loop, claim):
        from concurrent.futures import Future
        self.loop, self.claim = loop, claim
        self.future = Future()
        self.lock = Lock()
        self.revoked = False
        self.deadline = monotonic()+CLAIM_TIMEOUT

    def revoke(self):
        with self.lock:
            self.revoked = True
            if not self.future.done(): self.future.set_result(None)

    def _deliver(self):
        with self.lock:
            if self.revoked or monotonic() >= self.deadline or self.future.done():
                if not self.future.done(): self.future.set_result(None)
                return
            try:
                result = self.claim()  # 同loop、同步、无await；执行完前worker不能放Runtime锁。
            except Exception:
                result = None
            self.future.set_result(result)

    def wait(self):
        try:
            self.loop.call_soon_threadsafe(self._deliver)
            return self.future.result(timeout=max(0, self.deadline-monotonic()))
        except (ThreadTimeout, RuntimeError):
            # 若loop已经正在领取，此锁等它结束，Runtime仍持锁；否则撤销迟到回调。
            self.revoke()
            return self.future.result()


class VoiceProposalHost:
    """同一宿主loop的受限RPC目标；鉴权由HTTP层完成，随机ID只负责作用域。"""

    def __init__(self, runtime_provider, enabled=False):
        if not callable(runtime_provider) or type(enabled) is not bool:
            raise ValueError('voice_proposal_configuration_invalid')
        self._provider, self.enabled = runtime_provider, enabled
        self._owner = secrets.token_hex(16)
        self._loop = self._executor = self._slots = None
        self._controllers = self._budget = None
        self._connections, self._snapshots = {}, {}
        self._workers, self._gates = set(), {}
        self._operations = 0
        self._closed = False

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError('voice_proposal_event_loop_mismatch')
        self._loop = loop

    def _available(self):
        self._check_loop()
        if not self.enabled or self._closed or self._operations >= MAX_OPERATIONS:
            return False
        self._operations += 1
        for sid, entry in tuple(self._snapshots.items()):
            if monotonic() >= entry.expires:
                self._snapshots.pop(sid, None)
        return True

    def _invalidate(self, cid, state):
        state.generation += 1
        for sid, entry in tuple(self._snapshots.items()):
            if entry.connection_id == cid: self._snapshots.pop(sid, None)
        for gate, owner in tuple(self._gates.items()):
            if owner == cid: gate.revoke()

    def _connection(self, cid, stamp, *, create=False, advance=False):
        state = self._connections.get(cid)
        if state is None:
            if not create or len(self._connections) >= MAX_CONNECTIONS: return None
            state = self._connections[cid] = _Connection(stamp)
        if state.closed: return None
        old_turn, old_revision, old_epoch = state.stamp
        turn, revision, epoch = stamp
        if turn < old_turn or epoch < old_epoch or (turn == old_turn and revision < old_revision): return None
        if stamp != state.stamp:
            if not advance: return None
            self._invalidate(cid, state)
            state.stamp = stamp
            if state.controller is not None:
                p = self._controllers[0]
                state.controller.revised(turn=p.TurnStamp(*stamp))
        return state

    async def _runtime_call(self, function, *args, **kwargs):
        """超时不退物理worker名额；迟到读取不进入快照/正式输出。"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='voice-proposal-runtime')
            self._slots = asyncio.Semaphore(2)
        await asyncio.wait_for(self._slots.acquire(), timeout=.05)
        try:
            future = self._loop.run_in_executor(self._executor, lambda: function(*args, **kwargs))
        except BaseException:
            self._slots.release(); raise
        self._workers.add(future)
        def finished(result):
            self._workers.discard(result)
            self._slots.release()
            if not result.cancelled(): result.exception()
        future.add_done_callback(finished)
        return await asyncio.wait_for(asyncio.shield(future), timeout=RUNTIME_TIMEOUT)

    def _entry(self, sid, cid, stamp):
        if not isinstance(sid, str) or re.fullmatch(r'[0-9a-f]{32}', sid) is None:
            return None
        entry = self._snapshots.get(sid)
        state = self._connection(cid, stamp)
        if (entry is None or state is None or entry.connection_id != cid or entry.stamp != stamp
                or entry.generation != state.generation or entry.consumed or monotonic() >= entry.expires):
            return None
        return entry

    async def snapshot(self, body):
        stamp = _scope(body, {'query', 'session_id'})
        query, session = _text(body['query']), _session(body['session_id'])
        limit = 5
        miss = _miss('snapshot')
        if not self._available(): return miss
        cid = body['connection_id']
        state = self._connection(cid, stamp, create=True, advance=True)
        if state is None: return miss
        generation = state.generation
        try:
            runtime = self._provider()  # 只领取现有Runtime；不调用bootstrap/创建库。
            receipt = deepcopy(await self._runtime_call(runtime.candidate_memory_snapshot, query, limit=limit))
            engine = receipt['engine']
            if (type(engine.get('protocol')) is not int or engine['protocol'] != 1
                    or engine.get('read_status') != 'readable' or not isinstance(engine.get('items'), list)
                    or len(engine['items']) > limit+1+3+3 or not isinstance(engine.get('snapshot_token'), str)
                    or not engine['snapshot_token'] or len(engine['snapshot_token']) > 8192
                    or not isinstance(engine.get('memory_digest'), str) or re.fullmatch(r'[0-9a-f]{64}', engine['memory_digest']) is None
                    or not isinstance(receipt.get('runtime_revision'), str) or not 1 <= len(receipt['runtime_revision']) <= 256):
                return miss
            rows = engine['items']
            # AB的limit仅约束normal；profile/L6/L7是独立通道，不截断正式所需投影。
            caps = {'normal': limit, 'profile': 1, 'schema': 3, 'proactive': 3}
            counts = dict.fromkeys(caps, 0)
            if any(not isinstance(row, dict) or not isinstance(row.get('content'), str)
                   or not isinstance(row.get('memory_id'), str) or not 1 <= len(row['memory_id']) <= 256
                   or not isinstance(row.get('source_event_ids'), list) or len(row['source_event_ids']) > 1024
                   or any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in row['source_event_ids']) for row in rows): return miss
            for row in rows:
                channel = row.get('channel')
                if not isinstance(channel, str) or channel not in caps: return miss
                counts[channel] += 1
                if counts[channel] > caps[channel]: return miss
            context = '\n'.join(row['content'] for row in rows)
            if (len(context) > 16000 or len(context.encode('utf-8')) > MAX_CONTEXT_BYTES
                    or len(json.dumps(receipt, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')) > MAX_SNAPSHOT_BYTES
                    or self._closed or state.closed or state.generation != generation): return miss
            # 每连接仅保留一个快照；同代次新快照也撤销旧候选及领取门。
            self._invalidate(cid, state)
            if state.controller is not None: state.controller.context_changed()
            sid = secrets.token_hex(16)
            self._snapshots[sid] = _Snapshot(cid, stamp, state.generation, query, session, receipt,
                runtime, context, monotonic()+SNAPSHOT_TTL)
            return {'version': 1, 'state': 'ready', 'snapshot_id': sid, 'memory_context': context, 'reason_code': None}
        except asyncio.CancelledError:
            raise
        except Exception:
            return miss

    async def start(self, body):
        stamp = _scope(body, {'snapshot_id', 'messages', 'tools_required'})
        if type(body['tools_required']) is not bool: raise ValueError('voice_proposal_request_invalid')
        _session(body['snapshot_id'])
        messages = _messages(body['messages'])
        miss = _miss('start')
        if body['tools_required'] is not False: return _miss('start', 'tools_required')
        if not self._available(): return miss
        cid = body['connection_id']
        entry = self._entry(body['snapshot_id'], cid, stamp)
        if entry is None: return miss
        state = self._connections[cid]
        if state.attempted_turn == stamp[0]: return miss
        try:
            if self._provider() is not entry.runtime: return miss
            binding = await self._runtime_call(entry.runtime.candidate_model_binding)
            if self._entry(body['snapshot_id'], cid, stamp) is not entry or state.attempted_turn == stamp[0]: return miss
            if binding.get('campus_free_verified') is not True or not isinstance(binding.get('policy_revision'), str): return miss
            if self._controllers is None:
                self._controllers = _load_controllers()
                self._budget = self._controllers[0].RequestBudget()
            p, stream = self._controllers
            if state.controller is None:
                model = stream.GatewayPreparationModel(**{key: binding[key] for key in ('open_response', 'model', 'campus_free_verified')})
                state.controller = p.VoicePreemptive(model, self._budget, limits=p.Limits(enabled=True))
            elif entry.policy_revision is None:
                # 已有连接也须使用本次政策；模型/策略变更不能复用旧控制器。
                old = getattr(state.controller, '_host_policy_revision', None)
                if old != binding['policy_revision']:
                    state.retired.append(state.controller)
                    state.controller.close()
                    model = stream.GatewayPreparationModel(**{key: binding[key] for key in ('open_response', 'model', 'campus_free_verified')})
                    state.controller = p.VoicePreemptive(model, self._budget, limits=p.Limits(enabled=True))
            state.controller._host_policy_revision = binding['policy_revision']
            entry.messages, entry.policy_revision = messages, binding['policy_revision']
            version = p.SnapshotVersion(_digest({'runtime': entry.receipt['runtime_revision'],
                'memory': entry.receipt['engine']['memory_digest']}), _digest(messages), 'none', binding['policy_revision'])
            entry.context = p.ContextSnapshot(version, messages)
            turn = p.TurnStamp(*stamp)
            scope = p.RequestScope(self._owner, cid, turn, stamp[1])
            state.attempted_turn = stamp[0]
            started = state.controller.provisional(turn=turn, transcript=entry.query, context=entry.context, scope=scope)
            return {'version': 1, 'state': 'preparing' if started else 'miss', 'reason_code': None if started else 'not_admitted'}
        except asyncio.CancelledError:
            raise
        except Exception:
            return miss

    async def confirm(self, body):
        stamp = _scope(body, {'snapshot_id', 'query', 'messages', 'tools_required', 'formal_turn_id', 'client_round_id', 'session_id'})
        _session(body['snapshot_id'])
        transcript, session = _text(body['query']), _session(body['session_id'])
        messages = _messages(body['messages'])
        formal, client = body['formal_turn_id'], body['client_round_id']
        try:
            if not isinstance(formal, str) or str(UUID(formal)) != formal: raise ValueError
            if not isinstance(client, str) or re.fullmatch(r'[0-9a-f]{24,32}', client) is None: raise ValueError
        except ValueError: raise ValueError('voice_proposal_request_invalid') from None
        miss = _miss('confirm')
        if type(body['tools_required']) is not bool:
            raise ValueError('voice_proposal_request_invalid')
        if body.get('tools_required', False) is not False or not self._available(): return miss
        cid = body['connection_id']
        state = self._connection(cid, stamp)
        if state is None or state.controller is None: return miss
        sid = body['snapshot_id']
        entry = self._entry(sid, cid, stamp)
        if (entry is None or entry.messages != messages or entry.query != transcript or entry.session_id != session):
            state.controller.context_changed()
            return miss
        gate = None
        adopted = False
        try:
            if self._provider() is not entry.runtime: return miss
            p = self._controllers[0]
            turn = p.TurnStamp(*stamp)
            lease = await state.controller.confirmed(turn=turn, transcript=transcript, context=entry.context)
            if lease is None or self._entry(sid, cid, stamp) is not entry: return miss
            def loop_claim():
                if self._closed or self._entry(sid, cid, stamp) is not entry or self._provider() is not entry.runtime: return None
                text = lease.claim(turn=turn, context=entry.context)
                if text is not None:
                    entry.consumed = True
                    self._snapshots.pop(sid, None)
                return text
            gate = _ClaimGate(self._loop, loop_claim)
            self._gates[gate] = cid
            def worker_claim():
                if entry.runtime.candidate_policy_revision() != entry.policy_revision: return None
                return gate.wait()
            result = await self._runtime_call(entry.runtime.claim_candidate_memory, entry.receipt,
                query=transcript, formal_turn_id=formal, client_round_id=client, session_id=session, claim=worker_claim)
            if not isinstance(result, str) or not result.strip() or len(result) > 2048: return miss
            if (self._closed or state.closed or state.stamp != stamp or state.generation != entry.generation
                    or self._provider() is not entry.runtime): return miss
            adopted = True
            return {'version': 1, 'state': 'adopted', 'text': result, 'reason_code': None}
        except asyncio.CancelledError:
            if gate is not None: gate.revoke()
            self._invalidate(cid, state)
            state.controller.context_changed()
            raise
        except Exception:
            return miss
        finally:
            if gate is not None:
                gate.revoke()
                self._gates.pop(gate, None)
                if not adopted and self._entry(sid, cid, stamp) is entry:
                    self._snapshots.pop(sid, None)
                    if state.controller is not None: state.controller.context_changed()

    async def _settle(self, state):
        controllers = list(state.retired)
        if state.controller is not None:
            controllers.append(state.controller)
            state.retired.append(state.controller)
            state.controller = None
        if not controllers: return True
        results = await finish_before_cancel(asyncio.gather(
            *(controller.aclose(timeout_seconds=CLOSE_TIMEOUT) for controller in controllers), return_exceptions=True))
        for controller, result in zip(controllers, results):
            if result is True and controller in state.retired: state.retired.remove(controller)
        return all(result is True for result in results)

    async def cancel(self, body):
        return await self._cancel(body, closing=False)

    async def close(self, body):
        return await self._cancel(body, closing=True)

    async def _cancel(self, body, *, closing):
        stamp = _scope(body)
        self._check_loop()
        cid = body['connection_id']
        if cid not in self._connections:
            # 控制消息可先于迟到snapshot到达；封住同轮，close还封住整个连接。
            if len(self._connections) < MAX_CONNECTIONS:
                self._connections[cid] = _Connection(stamp, closed=closing, attempted_turn=stamp[0])
            return _cancel_result(True, closing=closing)
        state = self._connection(cid, stamp, advance=True)
        if state is None:
            existing = self._connections.get(cid)
            if existing is not None and existing.stamp != stamp:
                old_turn, old_revision, old_epoch = existing.stamp
                if stamp[0] != old_turn or stamp[1] < old_revision or stamp[2] < old_epoch:
                    raise RuntimeError('voice_proposal_rejected')
                existing.stamp = stamp
                self._invalidate(cid, existing)
            done = True if existing is None else await self._settle(existing)
            return _cancel_result(done, closing=closing)
        self._invalidate(cid, state)
        state.closed = closing
        state.attempted_turn = max(state.attempted_turn, stamp[0])
        if state.controller is not None:
            state.controller.cancel(turn_id=stamp[0], cancel_epoch=stamp[2])
        done = await self._settle(state)
        return _cancel_result(done, closing=closing)

    async def aclose(self):
        self._check_loop()
        self._closed = True
        for cid, state in self._connections.items():
            self._invalidate(cid, state)
            state.closed = True
        settled = await finish_before_cancel(asyncio.gather(
            *(self._settle(state) for state in self._connections.values()), return_exceptions=True))
        if self._workers:
            _, pending = await asyncio.wait(tuple(self._workers), timeout=RUNTIME_TIMEOUT)
        else:
            pending = set()
        done = all(result is True for result in settled) and not pending
        if self._executor is not None: self._executor.shutdown(wait=False, cancel_futures=True)
        self._snapshots.clear()
        return {'version': 1, 'closed': done, 'owned_upstream_exited': all(result is True for result in settled),
                'provider_compute_stopped': False}
