"""实际执行器组合保留AE与诊断上下文，不依赖模型或原生资源。"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path
import threading
from types import SimpleNamespace as NS

import pytest


@pytest.mark.parametrize('revoke', [False,True])
def test_submission_stamp_survives_real_ae_and_diagnostic_executor_layers(monkeypatch,revoke):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]/'scripts/development/xiaozhi'))
    import voice_completion as completion
    import voice_interruption as guard
    import voice_proposal_adapter as proposal
    from voice_diagnostics import ContextExecutor
    marker=ContextVar('synthetic_marker',default=None)
    sentinel=object()
    class Connection:
        _longmemory_audio_revocation_installed=True
        tts=NS(_longmemory_cosy_streaming_installed=True)
        sentence_id='synthetic'
        def chat(self,query):return completion.output_lease(self).current(),proposal._CHAT.get(),marker.get(),query
    conn=Connection();barrier=threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        busy=pool.submit(barrier.wait)
        native=ContextExecutor(pool,conn)
        ae=proposal._Executor(NS(_handoff=lambda c,q:sentinel),conn,native)
        executor=completion._CompletionExecutor(conn,ae)
        token=marker.set('kept')
        try:future=executor.submit(conn.chat,'synthetic-query')
        finally:marker.reset(token)
        if revoke:guard.state_for(conn).revoke('asr_handoff_revoked')
        barrier.set();busy.result(timeout=2)
        assert future.result(timeout=2)==(not revoke,sentinel,'kept','synthetic-query')
