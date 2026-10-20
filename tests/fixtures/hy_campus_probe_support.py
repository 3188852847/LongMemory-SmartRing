"""独立合成校园探针的持久调用门；复用传入源码臂的免费账本契约。"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import local
from time import time
from uuid import uuid4


ARMS = frozenset(('baseline', 'candidate'))
STATES = frozenset(('reserved', 'completed', 'unknown'))
HALT_REASONS = frozenset(('parent_disconnected', 'cancelled', 'timeout', 'probe_failed',
                         'validation_failed', 'manual_stop'))
_INTERNAL_REASONS = HALT_REASONS | {'inflight_or_unknown', 'usage_unknown', 'finish_failed', 'limit_reached'}


class CampusProbeStopped(RuntimeError):
    """只有固定原因码；不得附加请求、凭据或底层异常正文。"""


def _path(path):
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise CampusProbeStopped('campus_probe_existing_ledger_required')
    return path


@contextmanager
def _open(path):
    path = _path(path)
    try:
        connection = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=5)
        try:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                yield connection
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        raise CampusProbeStopped('campus_probe_ledger_unavailable') from None


def _gate(connection):
    row = connection.execute('SELECT version,hard_limit,identity,halted,reason FROM probe_gate').fetchall()
    if (len(row) != 1 or row[0][0] != 1 or type(row[0][1]) is not int
            or not 1 <= row[0][1] <= 8 or row[0][3] not in (0, 1)
            or row[0][4] not in _INTERNAL_REASONS | {None}):
        raise CampusProbeStopped('campus_probe_gate_invalid')
    return row[0]


def _counts(connection):
    rows = connection.execute('SELECT calls.state,probe_arms.arm,COUNT(*) FROM calls '
        'LEFT JOIN probe_arms ON calls.id=probe_arms.attempt_id GROUP BY calls.state,probe_arms.arm').fetchall()
    if any(state not in STATES or arm not in ARMS for state, arm, _ in rows):
        raise CampusProbeStopped('campus_probe_attempts_invalid')
    if connection.execute('SELECT COUNT(*) FROM probe_arms').fetchone()[0] != sum(row[2] for row in rows):
        raise CampusProbeStopped('campus_probe_attempts_invalid')
    arms = {arm: {state: 0 for state in sorted(STATES)} for arm in sorted(ARMS)}
    states = {state: 0 for state in sorted(STATES)}
    for state, arm, count in rows:
        arms[arm][state] += count
        states[state] += count
    return states, arms


def _halt(connection, reason):
    connection.execute('UPDATE probe_gate SET halted=1,reason=COALESCE(reason,?)', (reason,))


def halt_calls(path, reason):
    if type(reason) is not str or reason not in HALT_REASONS:
        raise CampusProbeStopped('campus_probe_halt_reason_invalid')
    with _open(path) as connection:
        _gate(connection)
        _counts(connection)
        _halt(connection, reason)


def calls_snapshot(path):
    with _open(path) as connection:
        _, limit, _, halted, reason = _gate(connection)
        states, arms = _counts(connection)
        return {'version': 1, 'hard_limit': limit, 'halted': bool(halted), 'reason': reason,
                'attempt_count': sum(states.values()),
                'unknown_or_inflight': states['reserved'] + states['unknown'],
                'states': states, 'arms': arms, 'personal_cost_micro_cny': 0}


def limited_campus_calls(base_class, path, proof, *, create=False, arm='baseline', limit=8):
    """返回传入FreeCampusCalls的子类；两臂必须传相同proof/path/limit。"""
    if (type(limit) is not int or not 1 <= limit <= 8 or type(arm) is not str
            or arm not in ARMS or type(create) is not bool):
        raise CampusProbeStopped('campus_probe_options_invalid')
    if not isinstance(base_class, type) or getattr(base_class, 'billing_mode', None) != 'owner_confirmed_free':
        raise CampusProbeStopped('campus_probe_base_class_invalid')
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path:
        raise CampusProbeStopped('campus_probe_ledger_path_invalid')

    class LimitedCampusCalls(base_class):
        def __init__(self):
            self._probe_scope = local()
            self.arm = arm
            try:
                super().__init__(path, proof=proof, create=create)
                with self._connect() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    if create:
                        connection.execute('CREATE TABLE probe_gate (version INTEGER NOT NULL, hard_limit INTEGER NOT NULL, '
                            'identity TEXT NOT NULL, halted INTEGER NOT NULL, reason TEXT)')
                        connection.execute('CREATE TABLE probe_arms (attempt_id TEXT PRIMARY KEY, arm TEXT NOT NULL)')
                        connection.execute('INSERT INTO probe_gate VALUES (1,?,?,0,NULL)', (limit, self.identity))
                    _, actual_limit, identity, _, _ = _gate(connection)
                    if actual_limit != limit or identity != self.identity:
                        raise CampusProbeStopped('campus_probe_identity_changed')
                    states, _ = _counts(connection)
                    if states['reserved'] or states['unknown']:
                        _halt(connection, 'inflight_or_unknown')
            except CampusProbeStopped:
                raise
            except Exception:
                raise CampusProbeStopped('campus_probe_ledger_open_failed') from None

        @contextmanager
        def _connect(self):
            current = getattr(self._probe_scope, 'connection', None)
            if current is not None:
                yield current
                return
            try:
                with super()._connect() as connection:
                    yield connection
            except (OSError, sqlite3.Error):
                raise CampusProbeStopped('campus_probe_ledger_unavailable') from None

        def reserve(self, phase):
            if type(phase) is not str or phase not in {'hy', 'baseline', 'answer', 'probe'}:
                raise CampusProbeStopped('campus_probe_phase_invalid')
            aid, failure = None, None
            with self._connect() as connection:
                connection.execute('BEGIN IMMEDIATE')
                _, actual_limit, identity, halted, _ = _gate(connection)
                if actual_limit != limit or identity != self.identity:
                    raise CampusProbeStopped('campus_probe_identity_changed')
                states, _ = _counts(connection)
                if halted:
                    failure = 'campus_probe_halted'
                elif states['reserved'] or states['unknown']:
                    _halt(connection, 'inflight_or_unknown')
                    failure = 'campus_probe_inflight_or_unknown'
                elif sum(states.values()) >= limit:
                    _halt(connection, 'limit_reached')
                    failure = 'campus_probe_limit_reached'
                else:
                    aid = uuid4().hex
                    connection.execute("INSERT INTO calls VALUES (?,?,'reserved',NULL,NULL,NULL,?)", (aid, phase, time()))
                    connection.execute('INSERT INTO probe_arms VALUES (?,?)', (aid, arm))
            # 必须在事务提交之后抛出：暂停位不能被异常回滚抹去。
            if failure:
                raise CampusProbeStopped(failure)
            return aid

        def finish(self, aid, usage=None, *, successful=False):
            failure = None
            with self._connect() as connection:
                connection.execute('BEGIN IMMEDIATE')
                _gate(connection)
                row = connection.execute('SELECT calls.state,probe_arms.arm FROM calls LEFT JOIN probe_arms '
                    'ON calls.id=probe_arms.attempt_id WHERE calls.id=?', (aid,)).fetchone()
                if row != ('reserved', arm):
                    _halt(connection, 'finish_failed')
                    failure = 'campus_probe_attempt_not_reserved'
                else:
                    self._probe_scope.connection = connection
                    try:
                        # 原父类是usage有效性的唯一判定来源，保持费用0与原状态契约。
                        super().finish(aid, usage, successful=successful)
                    except Exception:
                        connection.execute("UPDATE calls SET state='unknown',prompt_tokens=NULL,completion_tokens=NULL,"
                            "total_tokens=NULL WHERE id=?", (aid,))
                        _halt(connection, 'finish_failed')
                        failure = 'campus_probe_finish_failed'
                    finally:
                        self._probe_scope.connection = None
                    state = connection.execute('SELECT state FROM calls WHERE id=?', (aid,)).fetchone()
                    if state != ('completed',):
                        _halt(connection, 'usage_unknown')
            if failure:
                raise CampusProbeStopped(failure)

        def status(self):
            try:
                result = super().status()
                snapshot = calls_snapshot(self.path)
                result.update(probe_hard_limit=snapshot['hard_limit'], probe_arms=snapshot['arms'])
                if snapshot['halted'] or snapshot['unknown_or_inflight']:
                    result.update(state='paused', reason='campus_probe_halted')
                return result
            except Exception:
                return {'state': 'paused', 'reason': 'campus_probe_ledger_unavailable',
                        'billing_policy': self.billing_mode}

    return LimitedCampusCalls()
