"""免费校园合成账本的跨臂硬门；不执行任何模型或HTTP调用。"""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from longmemory.infrastructure.config.campus_calls import FreeCampusCalls


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('hy_campus_probe_support', ROOT / 'tests/fixtures/hy_campus_probe_support.py')
support = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(support)
STOP = support.CampusProbeStopped
PROOF = {'request_model': 'synthetic-campus-model', 'billing_mode': 'owner_confirmed_free',
         'personal_cost_micro_cny': 0, 'source': 'owner_confirmation',
         'credential_sha256': 'c' * 64, 'endpoint_sha256': 'e' * 64}
USAGE = {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}


def open_calls(path, *, create=False, arm='baseline', limit=8, proof=PROOF, base=FreeCampusCalls):
    return support.limited_campus_calls(base, path, proof, create=create, arm=arm, limit=limit)


def test_two_arms_share_all_eight_completed_calls_and_no_reset_on_reopen(tmp_path):
    path = tmp_path / 'synthetic.db'
    first = open_calls(path, create=True)
    assert isinstance(first, FreeCampusCalls)
    for number in range(8):
        calls = open_calls(path, arm=('baseline' if number % 2 == 0 else 'candidate'))
        aid = calls.reserve('probe')
        calls.finish(aid, USAGE, successful=True)
    snapshot = support.calls_snapshot(path)
    assert snapshot['attempt_count'] == 8 and snapshot['states'] == {'completed': 8, 'reserved': 0, 'unknown': 0}
    assert snapshot['arms']['baseline']['completed'] == snapshot['arms']['candidate']['completed'] == 4
    assert snapshot['personal_cost_micro_cny'] == 0
    with pytest.raises(STOP, match='^campus_probe_limit_reached$'):
        first.reserve('answer')
    reopened = open_calls(path, arm='candidate')
    with pytest.raises(STOP, match='^campus_probe_halted$'):
        reopened.reserve('hy')
    assert support.calls_snapshot(path)['reason'] == 'limit_reached'
    assert reopened.status()['state'] == 'paused'
    assert reopened.status()['official_budget_reused_or_released'] is False
    assert reopened.status()['held_or_settled_upper_micro_cny'] == 0


def test_parent_usage_validation_and_gateway_diagnostics_are_reused(tmp_path):
    seen = []
    class ArmSpecificFreeCalls(FreeCampusCalls):
        def finish(self, aid, usage=None, *, successful=False):
            seen.append((aid, usage, successful))
            return super().finish(aid, usage, successful=successful)
    calls = open_calls(tmp_path / 'synthetic.db', create=True, base=ArmSpecificFreeCalls)
    assert isinstance(calls, ArmSpecificFreeCalls)
    aid = calls.reserve('answer')
    calls.finish(aid, USAGE, successful=True)
    assert seen == [(aid, USAGE, True)]
    calls.record_gateway_result(aid, status=200, done=True, forwarded=True, usage_seen=True)
    with sqlite3.connect(calls.path) as db:
        assert db.execute('SELECT status,done,forwarded,usage_seen FROM gateway_results').fetchone() == (200, 1, 1, 1)
    status = calls.status()
    assert status['observed_prompt_tokens'] == 2 and status['observed_completion_tokens'] == 3
    assert status['personal_cost_micro_cny'] == 0 and status['cost_authority'] == 'owner_confirmation'
    assert status['state'] == 'available'


@pytest.mark.parametrize('usage,successful', [(None, True), ({}, True),
    ({'prompt_tokens': -1, 'completion_tokens': 3, 'total_tokens': 2}, True),
    ({'prompt_tokens': True, 'completion_tokens': 3, 'total_tokens': 4}, True),
    ({'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 6}, True), (USAGE, False)])
def test_invalid_or_missing_usage_is_unknown_and_permanently_halted(tmp_path, usage, successful):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    calls.finish(calls.reserve('hy'), usage, successful=successful)
    snapshot = support.calls_snapshot(path)
    assert snapshot['halted'] and snapshot['states']['unknown'] == 1
    assert snapshot['attempt_count'] == 1 and snapshot['reason'] == 'usage_unknown'
    with pytest.raises(STOP, match='^campus_probe_halted$'):
        open_calls(path, arm='candidate').reserve('probe')


@pytest.mark.parametrize('after_update', [False, True])
def test_parent_finish_exception_still_commits_unknown_and_halt(tmp_path, after_update):
    class FailingFinish(FreeCampusCalls):
        def finish(self, aid, usage=None, *, successful=False):
            if after_update:
                super().finish(aid, usage, successful=successful)
            raise RuntimeError('synthetic-private-exception-body')
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True, base=FailingFinish)
    with pytest.raises(STOP, match='^campus_probe_finish_failed$') as error:
        calls.finish(calls.reserve('probe'), USAGE, successful=True)
    assert 'private' not in str(error.value)
    snapshot = support.calls_snapshot(path)
    assert snapshot['halted'] and snapshot['states']['unknown'] == 1
    with pytest.raises(STOP):
        open_calls(path, arm='candidate').reserve('probe')


def test_second_reserve_persists_halt_without_releasing_first_reservation(tmp_path):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    aid = calls.reserve('probe')
    with pytest.raises(STOP, match='^campus_probe_inflight_or_unknown$'):
        calls.reserve('answer')
    assert support.calls_snapshot(path)['states']['reserved'] == 1
    calls.finish(aid, USAGE, successful=True)
    assert support.calls_snapshot(path)['states']['completed'] == 1
    with pytest.raises(STOP, match='^campus_probe_halted$'):
        open_calls(path, arm='candidate').reserve('answer')


def test_readonly_snapshot_does_not_halt_a_valid_live_first_attempt(tmp_path):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    aid = calls.reserve('probe')
    assert not support.calls_snapshot(path)['halted']
    assert calls.status()['state'] == 'paused'
    calls.finish(aid, USAGE, successful=True)
    assert calls.status()['state'] == 'available'
    calls.finish(calls.reserve('answer'), USAGE, successful=True)
    assert support.calls_snapshot(path)['attempt_count'] == 2


def test_reopening_with_reserved_attempt_commits_halt_and_preserves_reserved(tmp_path):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    calls.reserve('hy')
    reopened = open_calls(path, arm='candidate')
    assert support.calls_snapshot(path)['halted']
    assert support.calls_snapshot(path)['states']['reserved'] == 1
    with pytest.raises(STOP, match='^campus_probe_halted$'):
        reopened.reserve('probe')


def test_parent_disconnect_halt_is_persistent_and_does_not_change_reserved_to_completed(tmp_path):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    calls.reserve('answer')
    support.halt_calls(path, 'parent_disconnected')
    support.halt_calls(path, 'cancelled')
    snapshot = support.calls_snapshot(path)
    assert snapshot['reason'] == 'parent_disconnected' and snapshot['states']['reserved'] == 1
    assert snapshot['arms']['baseline']['reserved'] == 1
    with pytest.raises(STOP):
        open_calls(path, arm='candidate').reserve('probe')
    encoded = json.dumps(snapshot)
    assert 'synthetic-campus-model' not in encoded and 'credential' not in encoded and 'endpoint' not in encoded
    assert 'payload' not in encoded and 'prompt' not in encoded


def test_concurrent_separate_instances_cannot_pass_existing_reservation(tmp_path):
    path = tmp_path / 'synthetic.db'
    baseline = open_calls(path, create=True)
    candidate = open_calls(path, arm='candidate')
    start = Barrier(13)
    def reserve(number):
        calls = baseline if number % 2 == 0 else candidate
        start.wait(timeout=5)
        try:
            return calls, calls.reserve('probe')
        except STOP:
            return None
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(reserve, number) for number in range(12)]
        start.wait(timeout=5)
        winners = [value for future in futures if (value := future.result(timeout=10)) is not None]
    assert len(winners) == 1
    snapshot = support.calls_snapshot(path)
    assert snapshot['attempt_count'] == 1 and snapshot['halted'] and snapshot['states']['reserved'] == 1
    assert snapshot['attempt_count'] <= 8


@pytest.mark.parametrize('change', ['proof', 'limit'])
def test_changed_identity_or_limit_is_rejected_without_reset(tmp_path, change):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True, limit=4)
    calls.finish(calls.reserve('probe'), USAGE, successful=True)
    before = support.calls_snapshot(path)
    kwargs = {'limit': 5} if change == 'limit' else {'limit': 4, 'proof': PROOF | {'request_model': 'different'}}
    with pytest.raises(STOP):
        open_calls(path, arm='candidate', **kwargs)
    assert support.calls_snapshot(path) == before


@pytest.mark.parametrize('limit', [0, 9, -1, True, 1.5, None])
def test_limit_must_be_explicit_integer_one_through_eight(tmp_path, limit):
    with pytest.raises(STOP, match='^campus_probe_options_invalid$'):
        open_calls(tmp_path / 'never-created.db', create=True, limit=limit)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('phase', ['unknown', '', None, ['probe']])
def test_phase_whitelist_rejects_without_reserving(tmp_path, phase):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    with pytest.raises(STOP, match='^campus_probe_phase_invalid$'):
        calls.reserve(phase)
    assert support.calls_snapshot(path)['attempt_count'] == 0


def test_missing_ledger_and_unknown_halt_reason_never_create_a_file(tmp_path):
    path = tmp_path / 'missing.db'
    for operation in (lambda: open_calls(path), lambda: support.calls_snapshot(path),
                      lambda: support.halt_calls(path, 'cancelled')):
        with pytest.raises(STOP):
            operation()
    with pytest.raises(STOP, match='^campus_probe_halt_reason_invalid$'):
        support.halt_calls(path, 'synthetic-private-error')
    assert not path.exists()


def test_corrupt_or_unreadable_ledger_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic-private-ledger-detail')
    monkeypatch.setattr(support.sqlite3, 'connect', unavailable)
    assert calls.status()['state'] == 'paused'
    for operation in (lambda: calls.reserve('probe'), lambda: support.calls_snapshot(path),
                      lambda: support.halt_calls(path, 'probe_failed')):
        with pytest.raises(STOP, match='^campus_probe_ledger_unavailable$'):
            operation()


def test_deleted_attempt_mapping_or_orphan_mapping_cannot_reset_count(tmp_path):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    aid = calls.reserve('probe')
    calls.finish(aid, USAGE, successful=True)
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM calls WHERE id=?', (aid,))
    with pytest.raises(STOP, match='^campus_probe_attempts_invalid$'):
        calls.reserve('probe')


@pytest.mark.parametrize('limit', [1, 2, 8])
def test_configured_hard_limit_counts_all_completed_attempts(tmp_path, limit):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True, limit=limit)
    for _ in range(limit):
        calls.finish(calls.reserve('probe'), USAGE, successful=True)
    with pytest.raises(STOP, match='^campus_probe_limit_reached$'):
        calls.reserve('probe')
    assert support.calls_snapshot(path)['attempt_count'] == limit


def test_real_corrupt_sqlite_file_cannot_be_recreated_or_used(tmp_path):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    path.write_bytes(b'synthetic-invalid-sqlite')
    assert calls.status()['state'] == 'paused'
    for operation in (lambda: calls.reserve('probe'), lambda: support.calls_snapshot(path),
                      lambda: support.halt_calls(path, 'cancelled'), lambda: open_calls(path)):
        with pytest.raises(STOP):
            operation()
    assert path.read_bytes() == b'synthetic-invalid-sqlite'


def test_finish_from_other_arm_cannot_claim_or_release_a_reservation(tmp_path):
    path = tmp_path / 'synthetic.db'
    first = open_calls(path, create=True)
    second = open_calls(path, arm='candidate')
    aid = first.reserve('probe')
    with pytest.raises(STOP, match='^campus_probe_attempt_not_reserved$'):
        second.finish(aid, USAGE, successful=True)
    snapshot = support.calls_snapshot(path)
    assert snapshot['halted'] and snapshot['arms']['baseline']['reserved'] == 1
    assert snapshot['arms']['candidate']['completed'] == 0


def test_create_existing_ledger_does_not_overwrite_it(tmp_path):
    path = tmp_path / 'synthetic.db'
    calls = open_calls(path, create=True)
    calls.finish(calls.reserve('probe'), USAGE, successful=True)
    before = path.read_bytes()
    with pytest.raises(STOP):
        open_calls(path, create=True)
    assert path.read_bytes() == before and support.calls_snapshot(path)['attempt_count'] == 1


@pytest.mark.parametrize('reason', sorted(support.HALT_REASONS))
def test_all_documented_parent_stop_reasons_are_persistent(tmp_path, reason):
    path = tmp_path / 'synthetic.db'
    open_calls(path, create=True)
    support.halt_calls(path, reason)
    assert support.calls_snapshot(path)['reason'] == reason
    with pytest.raises(STOP, match='^campus_probe_halted$'):
        open_calls(path, arm='candidate').reserve('probe')
