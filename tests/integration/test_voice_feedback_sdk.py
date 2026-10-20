"""真实SDK/平台轮次/反馈账本；候选宿主关闭时也不能破坏正式反馈路径。"""

import os
from pathlib import Path
from types import SimpleNamespace
from time import monotonic, sleep
from uuid import uuid4

import pytest

from longmemory.bootstrap import build_backend_runtime
from longmemory.application.round_screen_turns import memory_receipt
import test_hy_semantic_sdk as sdk_fixture


SDK = Path(os.environ.get('LONGMEMORY_TEST_HY_PYTHON', 'missing-owner-sdk'))
pytestmark = pytest.mark.skipif(not SDK.is_file(), reason='explicit owner-installed fixed SDK required')


@pytest.mark.parametrize('same_session', [False, True])
def test_actual_sdk_feedback_dict_preserves_session_scope_and_rejects_existing_candidate(tmp_path, same_session):
    assembly = sdk_fixture.open_backend(tmp_path, scenario='projection')
    runtime = build_backend_runtime(assembly)
    engine = assembly.method.engine
    try:
        first, _ = runtime.prepare_round_screen('检查资料', client_round_id=uuid4().hex, session_id='a' * 32)
        runtime.complete_round_screen(turn_id=first.event.event_id, answer='合成回答', receipt=memory_receipt(first))
        runtime.wait_for_deferred_observations()
        until = monotonic() + 15
        while True:
            counts = engine.sdk_call('semantic_status')['task_counts']
            if not (counts.get('pending', 0) or counts.get('running', 0)):
                break
            assert monotonic() < until
            sleep(.02)
        # 默认无VoiceProposalHost/ASR安装。单独构造先前已取得的只读候选，
        # 确认正式反馈无论是否记录成功，都不能被该候选覆盖。
        runtime._model_service = SimpleNamespace(gateway=SimpleNamespace(
            encoder=SimpleNamespace(identity='synthetic-eight'),
            embed=lambda *_args: {'data': [{'embedding': [1.0] + [0.0] * 7}]}),
            close=lambda: None, pause_notice=lambda: None, status=lambda: {'state': 'available'})
        text = '你刚才记错了'
        candidate = runtime.candidate_memory_snapshot(text)
        assert candidate['engine']['read_status'] == 'readable'
        assert engine.candidate_validate(snapshot_token=candidate['engine']['snapshot_token'],
            memory_digest=candidate['engine']['memory_digest'])['valid']
        session, client = ('a' if same_session else 'f') * 32, uuid4().hex
        prepared, feedback = runtime.prepare_round_screen(text, client_round_id=client, session_id=session)
        assert isinstance(feedback, dict) and feedback['recorded'] is same_session
        if same_session:
            assert feedback['target_user_message_id'] == first.event.event_id
        assert runtime._proposal_formal[prepared.event.event_id]['eligible'] is False
        assert runtime.claim_candidate_memory(candidate, query=text, formal_turn_id=prepared.event.event_id,
            client_round_id=client, session_id=session,
            claim=lambda: pytest.fail('feedback must never adopt an existing candidate')) is None
        runtime.cancel_round_screen(prepared.event.event_id, reason='cancelled', client_round_id=client)
    finally:
        runtime.close()
