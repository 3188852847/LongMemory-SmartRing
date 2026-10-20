import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('waiting_handoff_fixture',ROOT/'tests/fixtures/voice_waiting_handoff.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
pytestmark=pytest.mark.skipif(not fixture.UPSTREAM.is_dir(),reason='owner-installed pinned upstream source absent')


def test_pinned_upstream_scheduler_stops_spending_slots_on_discarded_cue_tail():
    rows=fixture.comparison()['rows']
    for before,after in zip(rows[::2],rows[1::2]):
        assert before['answer_ready_ms']==after['answer_ready_ms']
        assert before['cue_frames']==after['cue_frames']
        if before['answer_ready_ms']==0:
            # 固定基线原来在回调丢弃提示，但仍耗掉调度器的时间槽。
            assert before['cue_frames_sent']==after['cue_frames_sent']==0
        else:
            assert before['cue_frames_sent']>after['cue_frames_sent']
        assert after['first_answer_sent_ms']==after['answer_ready_ms']
        assert before['first_answer_sent_ms']>after['first_answer_sent_ms']
