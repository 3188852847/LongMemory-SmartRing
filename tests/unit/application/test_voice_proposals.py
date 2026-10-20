"""宿主+实际AE控制器+实际AF网关/HTTP/SQLite；所有正文及Runtime均为合成。"""

import asyncio
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
from threading import Event, RLock, get_ident
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

import pytest

from longmemory.application import voice_proposals as module

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tests/unit/methods'))
from test_hy_candidate_response import gateway, complete_wire


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def controllers(monkeypatch):
    root = Path(os.environ.get('LONGMEMORY_TEST_PREEMPTIVE_SOURCES', str(ROOT/'scripts/development/xiaozhi')))
    if not (root/'voice_preemptive.py').is_file(): pytest.skip('explicit isolated AE source snapshot or combined tree required')
    p = load('af_host_test_preemptive', root/'voice_preemptive.py')
    s = load('af_host_test_preemptive_stream', root/'voice_preemptive_stream.py')
    if not hasattr(p, 'RequestScope'): pytest.skip('AE close ACK version required')
    monkeypatch.setattr(module, '_load_controllers', lambda: (p, s))
    return p, s


CID = 'a'*32
OTHER = 'b'*32
QUERY = '合成当前问题'
SESSION = 'b'*32
MESSAGES = [['system', '合成角色；以下是冻结记忆：合成记忆事实'], ['user', '合成旧问题'], ['assistant', '合成旧回答']]


def scope(cid=CID, turn=1, revision=0, epoch=0):
    return {'version': 1, 'connection_id': cid, 'turn_id': turn, 'transcript_revision': revision, 'cancel_epoch': epoch}


class Runtime:
    """隔离Runtime替身保留同一锁/fresh/正式来源核对；无prepare或写库接口。"""
    def __init__(self, server):
        self.server = server
        self.lock = RLock()
        self.policy = 'f'*64
        self.revision = 'synthetic-runtime:1'
        self.valid = self.formal_valid = True
        self.snapshots = self.claims = self.claimed = 0
        self.claim_threads = []
        self.claim_entered, self.allow_claim, self.lock_released = Event(), Event(), Event()
        self.allow_claim.set()
        self.snapshot_block = None

    def candidate_memory_snapshot(self, query, *, limit=5):
        self.snapshots += 1
        if self.snapshot_block: self.snapshot_block.wait(2)
        return {'engine': {'protocol': 1, 'read_status': 'readable', 'snapshot_token': 'SYNTHETIC_ENGINE_SECRET',
            'memory_digest': 'd'*64, 'items': [{'memory_id': 'synthetic-memory', 'content': '合成记忆事实', 'channel': 'normal',
                'source_event_ids': ['synthetic-source']}]}, 'runtime_revision': self.revision}

    def candidate_model_binding(self):
        return {**self.server.candidate_response_binding(), 'policy_revision': self.policy}

    def candidate_policy_revision(self):
        with self.lock: return self.policy

    def claim_candidate_memory(self, receipt, *, query, formal_turn_id, client_round_id, session_id, claim):
        with self.lock:
            try:
                self.claims += 1
                self.claim_threads.append(get_ident())
                self.claim_entered.set()
                self.allow_claim.wait(2)
                if (not self.valid or not self.formal_valid or receipt['runtime_revision'] != self.revision
                        or query != QUERY or session_id != SESSION): return None
                result = claim()
                if result is not None: self.claimed += 1
                return result
            finally: self.lock_released.set()


async def prepare(host, cid=CID, turn=1, *, messages=MESSAGES):
    common = scope(cid, turn)
    snapshot = await host.snapshot({**common, 'query': QUERY, 'session_id': SESSION})
    assert snapshot['state'] == 'ready'
    assert 'SYNTHETIC_ENGINE_SECRET' not in json.dumps(snapshot)
    started = await host.start({**common, 'snapshot_id': snapshot['snapshot_id'],
        'messages': deepcopy(messages), 'tools_required': False})
    assert started['state'] == 'preparing' and 'text' not in started
    return snapshot


def confirm_body(snapshot, **extra):
    return {**scope(), 'snapshot_id': snapshot['snapshot_id'], 'query': QUERY, 'messages': deepcopy(MESSAGES),
        'tools_required': False, 'formal_turn_id': str(uuid4()), 'client_round_id': 'c'*24, 'session_id': SESSION, **extra}


def test_default_disabled_never_gets_runtime_loads_ae_or_starts_worker():
    def fail(): pytest.fail('disabled host must not acquire runtime')
    async def run():
        host = module.VoiceProposalHost(fail)
        result = await host.snapshot({**scope(), 'query': QUERY, 'session_id': SESSION})
        assert result == {'version': 1, 'state': 'unavailable', 'snapshot_id': None, 'memory_context': None, 'reason_code': 'unavailable'}
        assert host._executor is host._controllers is None
        assert (await host.aclose())['closed']
    asyncio.run(run())


def test_full_actual_ae_af_http_budget_chain_adopts_once_on_loop_inside_runtime_lock(tmp_path, controllers, monkeypatch):
    with gateway(tmp_path, [{'body': complete_wire()}]) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            owner_thread = get_ident()
            original = controllers[0].ConfirmedCandidate.claim
            def checked(lease, **kwargs):
                assert get_ident() == owner_thread
                # Runtime的worker仍持锁；loop本身不可取得该锁。
                assert not runtime.lock.acquire(blocking=False)
                return original(lease, **kwargs)
            monkeypatch.setattr(controllers[0].ConfirmedCandidate, 'claim', checked)
            snapshot = await prepare(host)
            assert snapshot['memory_context'] == '合成记忆事实'
            request = confirm_body(snapshot)
            result = await host.confirm(request)
            assert result == {'version': 1, 'state': 'adopted', 'text': '合成回答', 'reason_code': None}
            assert (await host.confirm(request))['state'] == 'miss'
            assert runtime.claimed == 1 and runtime.claim_threads[0] != owner_thread
            assert (await host.aclose())['closed']
        asyncio.run(run())
        wire = json.loads(received[0]['body'])
        assert wire['messages'] == [{'role': r, 'content': text} for r, text in MESSAGES] + [{'role': 'user', 'content': QUERY}]
        assert len(received) == 1 and ledger.status()['unknown_or_inflight'] == 0


@pytest.mark.parametrize('change', ['query', 'messages', 'session', 'tools', 'revision', 'memory', 'formal', 'policy', 'runtime'])
def test_changed_actual_context_or_formal_memory_never_adopts(tmp_path, controllers, change):
    with gateway(tmp_path, [{'body': complete_wire()}]) as (server, ledger, received, _, __):
        runtime = Runtime(server); active = [runtime]
        async def run():
            host = module.VoiceProposalHost(lambda: active[0], enabled=True)
            snapshot = await prepare(host)
            request = confirm_body(snapshot)
            if change == 'query': request['query'] += '续说'
            elif change == 'messages': request['messages'][0][1] += '新时间/角色'
            elif change == 'session': request['session_id'] = 'f'*32
            elif change == 'tools': request['tools_required'] = True
            elif change == 'revision': request['transcript_revision'] = 1
            elif change == 'memory': runtime.valid = False
            elif change == 'formal': runtime.formal_valid = False
            elif change == 'policy': runtime.policy = 'e'*64
            else: active[0] = Runtime(server)
            result = await host.confirm(request)
            assert result['state'] == 'miss' and result['text'] is None
            assert runtime.claimed == 0
            await host.aclose()
        asyncio.run(run())


def test_foreign_snapshot_cancel_and_old_revision_cannot_touch_real_connection(tmp_path, controllers):
    with gateway(tmp_path, [{'body': complete_wire()}]) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            snapshot = await prepare(host)
            stolen = await host.start({**scope(OTHER), 'snapshot_id': snapshot['snapshot_id'], 'messages': MESSAGES, 'tools_required': False})
            assert stolen['state'] == 'miss'
            assert (await host.cancel(scope(OTHER)))['state'] == 'cancelled'
            with pytest.raises(RuntimeError, match='voice_proposal_rejected'):
                await host.cancel(scope(turn=0))
            assert (await host.confirm(confirm_body(snapshot)))['state'] == 'adopted'
            assert (await host.close(scope()))['state'] == 'closed'
            assert (await host.close(scope(epoch=2)))['state'] == 'closed'
            assert (await host.snapshot({**scope(), 'query': QUERY, 'session_id': SESSION}))['state'] == 'unavailable'
            await host.aclose()
        asyncio.run(run())
        assert len(received) == 1


@pytest.mark.parametrize('closing', [False, True])
def test_control_message_before_snapshot_seals_late_same_turn_requests(tmp_path, controllers, closing):
    with gateway(tmp_path, []) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            action = host.close if closing else host.cancel
            assert (await action(scope(epoch=1)))['owned_upstream_exited']
            old = await host.snapshot({**scope(), 'query': QUERY, 'session_id': SESSION})
            assert old['state'] == 'unavailable'
            same = await host.snapshot({**scope(epoch=1), 'query': QUERY, 'session_id': SESSION})
            if closing:
                assert same['state'] == 'unavailable'
            else:
                assert same['state'] == 'ready'
                result = await host.start({**scope(epoch=1), 'snapshot_id': same['snapshot_id'], 'messages': MESSAGES, 'tools_required': False})
                assert result['state'] == 'miss'
            await host.aclose()
        asyncio.run(run())
        assert not received


@pytest.mark.parametrize('mode', ['timeout', 'cancel'])
def test_worker_claim_timeout_or_cancellation_revokes_late_loop_callback_after_runtime_unlock(tmp_path, controllers, monkeypatch, mode):
    monkeypatch.setattr(module, 'CLAIM_TIMEOUT', .02)
    with gateway(tmp_path, [{'body': complete_wire()}]) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        deferred = []
        original = module._ClaimGate._deliver
        if mode == 'timeout': monkeypatch.setattr(module._ClaimGate, '_deliver', lambda gate: deferred.append(gate))
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            snapshot = await prepare(host)
            if mode == 'cancel': runtime.allow_claim.clear()
            task = asyncio.create_task(host.confirm(confirm_body(snapshot)))
            assert await asyncio.to_thread(runtime.claim_entered.wait, 1)
            if mode == 'timeout':
                assert (await task)['state'] == 'miss'
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                runtime.allow_claim.set()
            assert await asyncio.to_thread(runtime.lock_released.wait, 1)
            for gate in deferred: original(gate)  # Runtime锁已放开，迟到回调不得领取。
            await asyncio.sleep(.01)
            assert runtime.claimed == 0
            controller = host._connections[CID].controller
            assert controller.snapshot()['hits'] == 0
            assert (await host.aclose())['closed']
        try: asyncio.run(run())
        finally: runtime.allow_claim.set()


def test_actual_upstream_close_ack_keeps_host_slot_when_rpc_reports_closing(tmp_path, controllers, monkeypatch):
    monkeypatch.setattr(module, 'CLOSE_TIMEOUT', .02)
    with gateway(tmp_path, [{'mode': 'wait_headers', 'body': complete_wire()}]) as (server, ledger, received, first, release):
        entered, permit = Event(), Event()
        original = server._provider_transport._cancel_stream
        async def delayed(state):
            entered.set()
            while not permit.is_set(): await asyncio.sleep(.001)
            await original(state)
        monkeypatch.setattr(server._provider_transport, '_cancel_stream', delayed)
        runtime = Runtime(server)
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            await prepare(host)
            assert await asyncio.to_thread(first.wait, 1)
            reply = await host.cancel(scope(epoch=1))
            assert reply == {'version': 1, 'state': 'closing', 'owned_upstream_exited': False, 'provider_compute_stopped': False}
            assert host._budget.active == 1 and server._paid_lock.locked()
            assert (await host.confirm(confirm_body({'snapshot_id': '0'*32})))['state'] == 'miss'
            permit.set()
            for _ in range(100):
                if host._budget.active == 0: break
                await asyncio.sleep(.005)
            reply = await host.close(scope(epoch=1))
            assert reply['state'] == 'closed' and reply['owned_upstream_exited']
            assert host._budget.active == 0 and ledger.status()['unknown_or_inflight'] == 1
            await host.aclose()
        try: asyncio.run(run())
        finally: permit.set(); release.set()


def test_wrong_upstream_request_id_ack_quarantines_host_compute_slot(tmp_path, controllers):
    with gateway(tmp_path, [{'body': complete_wire()}]) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        original_binding = runtime.candidate_model_binding
        def binding():
            result = original_binding()
            original_open = result['open_response']
            def open_response(payload):
                handle = original_open(payload)
                original_wait = handle.wait_closed
                async def wrong_ack():
                    ack = await original_wait()
                    return dict(ack, request_id='0'*32)
                handle.wait_closed = wrong_ack
                return handle
            return dict(result, open_response=open_response)
        runtime.candidate_model_binding = binding
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            snapshot = await prepare(host)
            assert (await host.confirm(confirm_body(snapshot)))['state'] == 'miss'
            assert host._budget.active == 1
            assert host._connections[CID].controller.snapshot()['cleanup_unconfirmed'] == 1
            assert (await host.close(scope()))['state'] == 'closing'
            assert not (await host.aclose())['closed']
        asyncio.run(run())
        assert len(received) == 1  # 宿主保留名额不等于篡改已知用量的账本结算。


def test_two_timed_out_runtime_workers_remain_counted_and_third_cannot_start(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'RUNTIME_TIMEOUT', .02)
    class Blocked:
        calls = 0
        permit = Event()
        def candidate_memory_snapshot(self, *args, **kwargs):
            self.calls += 1; self.permit.wait(2); return {}
    runtime = Blocked()
    async def run():
        host = module.VoiceProposalHost(lambda: runtime, enabled=True)
        results = await asyncio.gather(*(host.snapshot({**scope(cid), 'query': QUERY, 'session_id': SESSION}) for cid in (CID, OTHER)))
        assert all(row['state'] == 'unavailable' for row in results)
        assert len(host._workers) == runtime.calls == 2
        assert (await host.snapshot({**scope('c'*32), 'query': QUERY, 'session_id': SESSION}))['state'] == 'unavailable'
        assert runtime.calls == 2 and len(host._workers) == 2
        runtime.permit.set()
        assert (await host.aclose())['closed']
    try: asyncio.run(run())
    finally: runtime.permit.set()


def test_snapshot_ttl_and_global_operation_budget_are_enforced(tmp_path, controllers, monkeypatch):
    monkeypatch.setattr(module, 'MAX_OPERATIONS', 2)
    with gateway(tmp_path, []) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            snapshot = await host.snapshot({**scope(), 'query': QUERY, 'session_id': SESSION})
            host._snapshots[snapshot['snapshot_id']].expires = -1
            assert (await host.start({**scope(), 'snapshot_id': snapshot['snapshot_id'], 'messages': MESSAGES, 'tools_required': False}))['state'] == 'miss'
            assert (await host.snapshot({**scope(), 'query': QUERY, 'session_id': SESSION}))['state'] == 'unavailable'
            assert runtime.snapshots == 1 and not received
            await host.aclose()
        asyncio.run(run())


@pytest.mark.parametrize('patch', [{'version': True}, {'turn_id': True}, {'connection_id': '../private'}, {'free_policy_verified': True}, {'transcript_revision': -1}, {'turn_id': 2**63}, {'session_id': None}, {'limit': 5}])
def test_malformed_scope_is_fixed_400_code_and_cannot_supply_free_authority(patch):
    async def run():
        host = module.VoiceProposalHost(lambda: pytest.fail('invalid request must not access runtime'), enabled=True)
        with pytest.raises(ValueError, match='^voice_proposal_request_invalid$'):
            await host.snapshot({**scope(), 'query': QUERY, 'session_id': SESSION, **patch})
        await host.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('messages', [[['user', 'x']], [['system', 'x'], ['system', 'y']], [['system', 'x'], ['tool', 'y']], [{'role': 'system', 'content': 'wrong-shape'}], [['system', 'x'*32001]]])
def test_messages_are_exact_bounded_context_pairs(messages):
    async def run():
        host = module.VoiceProposalHost(lambda: pytest.fail('invalid request must not access runtime'), enabled=True)
        with pytest.raises(ValueError, match='^voice_proposal_request_invalid$'):
            await host.start({**scope(), 'snapshot_id': '1'*32, 'messages': messages, 'tools_required': False})
        await host.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('change', ['none', 'context', 'source', 'invalid_token', 'runtime_revision'])
def test_real_ai_runtime_fresh_guard_is_called_before_loop_claim(tmp_path, controllers, change):
    path = Path(os.environ.get('LONGMEMORY_TEST_PROPOSAL_RUNTIME_SOURCE', str(ROOT/'src/longmemory/application/memory_runtime.py')))
    cls = load('af_host_actual_ai_runtime', path).MemoryRuntime
    if not hasattr(cls, 'claim_candidate_memory'): pytest.skip('AI Runtime candidate interface required')
    with gateway(tmp_path, [{'body': complete_wire()}]) as (server, ledger, received, _, __):
        # 仅构造该真实方法的隔离边界，没有打开库或创建日用Runtime。
        runtime = cls.__new__(cls)
        runtime._lock = RLock(); runtime._closed = runtime._closing = False
        runtime._use_enabled = True; runtime._proposal_instance = 'synthetic'; runtime._proposal_revision = 1
        runtime.backend_assembly = SimpleNamespace(legacy_sqlite=False)
        channels = ['profile', *['normal']*4, 'proactive']
        rows = [{'memory_id': f'synthetic-memory-{index}', 'content': f'合成{channel}记忆{index}',
                 'channel': channel, 'source_event_ids': [f'synthetic-source-{index}']} for index, channel in enumerate(channels)]
        context = '\n'.join(row['content'] for row in rows)
        messages = [['system', '合成角色；完整记忆：\n'+context]]
        runtime._method = SimpleNamespace(implementation_version='synthetic',
            candidate_snapshot=lambda **kwargs: {'protocol': 1, 'read_status': 'readable', 'snapshot_token': 'PRIVATE_ENGINE_TOKEN', 'memory_digest': 'd'*64, 'items': rows},
            candidate_validate=lambda **kwargs: {'protocol': 1, 'valid': True, 'memory_digest': 'd'*64})
        server.encoder = SimpleNamespace(identity='synthetic-encoder', encode_query=lambda text: [1.0])
        runtime._model_service = SimpleNamespace(gateway=server)
        formal = str(uuid4()); client = 'c'*24
        evidence = [{'item_id': row['memory_id'], 'rank': index+1, 'content_sha256': sha256(row['content'].encode()).hexdigest(), 'source_event_ids': row['source_event_ids']} for index, row in enumerate(rows)]
        runtime._proposal_formal = {formal: {'eligible': True, 'created': perf_counter(), 'client_round_id': client,
            'session_id': SESSION, 'query': runtime._proposal_digest(QUERY), 'context': runtime._proposal_digest(context), 'evidence': runtime._proposal_digest(evidence)}}
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            snapshot = await prepare(host, messages=messages)
            assert snapshot['memory_context'] == context and len(host._snapshots[snapshot['snapshot_id']].receipt['engine']['items']) == 6
            if change == 'context': runtime._proposal_formal[formal]['context'] = '0'*64
            elif change == 'source': runtime._proposal_formal[formal]['evidence'] = '0'*64
            elif change == 'invalid_token': runtime._method.candidate_validate = lambda **kwargs: {'protocol': 1, 'valid': False, 'memory_digest': 'd'*64}
            elif change == 'runtime_revision': runtime._proposal_revision += 1
            result = await host.confirm(confirm_body(snapshot, formal_turn_id=formal, client_round_id=client, messages=messages))
            if change == 'none':
                assert result['state'] == 'adopted' and result['text'] == '合成回答'
                assert formal not in runtime._proposal_formal
            else:
                assert result['state'] == 'miss' and result['text'] is None
                assert formal in runtime._proposal_formal
                assert host._connections[CID].controller.snapshot()['hits'] == 0
            await host.aclose()
        asyncio.run(run())


def test_same_turn_has_one_attempt_and_shared_model_total_budget_is_not_reset(tmp_path, controllers):
    with gateway(tmp_path, [{'body': complete_wire()}]) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            snapshot = await prepare(host)
            assert (await host.start({**scope(), 'snapshot_id': snapshot['snapshot_id'], 'messages': MESSAGES, 'tools_required': False}))['state'] == 'miss'
            assert (await host.confirm(confirm_body(snapshot)))['state'] == 'adopted'
            host._budget.max_requests = 1
            next_snapshot = await host.snapshot({**scope(OTHER), 'query': QUERY, 'session_id': SESSION})
            reply = await host.start({**scope(OTHER), 'snapshot_id': next_snapshot['snapshot_id'], 'messages': MESSAGES, 'tools_required': False})
            assert reply['state'] == 'miss' and host._budget.requests == 1
            assert (await host.aclose())['closed']
        asyncio.run(run())
        assert len(received) == ledger.status()['attempt_count'] == 1


@pytest.mark.parametrize('case', ['all_caps', 'normal_over', 'profile_over', 'schema_over', 'proactive_over', 'unknown_channel', 'context_over', 'receipt_bytes_over'])
def test_native_multichannel_caps_and_full_receipt_byte_bound_never_truncate(tmp_path, case):
    with gateway(tmp_path, []) as (server, ledger, received, _, __):
        runtime = Runtime(server)
        channels = ['profile', *['normal']*5, *['schema']*3, *['proactive']*3]
        if case.endswith('_over') and case.split('_')[0] in {'normal', 'profile', 'schema', 'proactive'}:
            channel = case.split('_')[0]
            caps = {'normal': 5, 'profile': 1, 'schema': 3, 'proactive': 3}
            channels = [channel]*(caps[channel]+1)
        elif case != 'all_caps': channels = ['unknown' if case == 'unknown_channel' else 'normal']
        rows = [{'memory_id': f'memory-{index}', 'channel': channel, 'content': f'完整条目-{index}',
                 'source_event_ids': [f'source-{index}']} for index, channel in enumerate(channels)]
        if case == 'context_over': rows[0]['content'] = '文'*16001
        if case == 'receipt_bytes_over': rows[0]['source_event_ids'] = ['源'*150+str(index) for index in range(500)]
        original = runtime.candidate_memory_snapshot
        def snapshot(query, **kwargs):
            result = original(query, **kwargs)
            result['engine']['items'] = deepcopy(rows)
            return result
        runtime.candidate_memory_snapshot = snapshot
        async def run():
            host = module.VoiceProposalHost(lambda: runtime, enabled=True)
            result = await host.snapshot({**scope(), 'query': QUERY, 'session_id': SESSION})
            if case == 'all_caps':
                assert result['state'] == 'ready'
                assert result['memory_context'] == '\n'.join(row['content'] for row in rows)
                assert host._snapshots[result['snapshot_id']].receipt['engine']['items'] == rows
            else:
                assert result['state'] == 'unavailable'
                assert result['snapshot_id'] is result['memory_context'] is None
                assert not host._snapshots
            assert not received
            await host.aclose()
        asyncio.run(run())


def test_actual_ae_rpc_strict_null_parser_accepts_disabled_host_dtos(controllers, monkeypatch):
    path = Path(os.environ.get('LONGMEMORY_TEST_PROPOSAL_RPC_SOURCE', str(ROOT/'scripts/development/xiaozhi/voice_proposal_rpc.py')))
    if not path.is_file(): pytest.skip('AE strict RPC source required in combined tree or explicit isolated snapshot')
    monkeypatch.setitem(sys.modules, 'voice_preemptive', controllers[0])
    rpc_module = load('af_host_strict_ae_rpc', path)
    async def run():
        host = module.VoiceProposalHost(lambda: pytest.fail('disabled host must not access runtime'))
        rpc = rpc_module.VoiceProposalRPC(1, 'e'*64, CID, 2, 1)
        async def post(operation, body, **kwargs):
            return await getattr(host, operation)(body)
        monkeypatch.setattr(rpc, '_post', post)  # DTO组合，不建立HTTP或声称网络已验。
        turn = rpc_module.TurnStamp(1, 0, 0)
        result = await rpc.snapshot(scope=turn, query=QUERY, session_id=SESSION)
        assert result['state'] == 'unavailable' and result['memory_context'] is None
        result = await rpc.start(scope=turn, snapshot_id='c'*32, messages=MESSAGES)
        assert result['state'] == 'miss' and 'text' not in result
        result = await rpc.confirm(scope=turn, snapshot_id='c'*32, query=QUERY, messages=MESSAGES,
            formal_turn_id=str(uuid4()), client_round_id='d'*24, session_id=SESSION)
        assert result['state'] == 'miss' and result['text'] is None
        assert (await rpc.close(scope=turn))['state'] == 'closed'
        assert (await host.aclose())['closed']
    asyncio.run(run())
