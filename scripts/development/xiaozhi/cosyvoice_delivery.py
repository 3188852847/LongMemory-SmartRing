"""Cosy交付模式的连接内故障降级；不读写偏好，不决定实机验收状态。"""
import threading

MODES = frozenset({"buffered", "incremental", "adaptive"})
ATTRIBUTE = "_longmemory_cosy_delivery_session"
FAILURES = frozenset({"before_handoff", "after_handoff", "reader_cleanup_timeout",
                      "reader_cleanup_unconfirmed", "configuration_changed"})
OUTCOMES = frozenset({"completed", "cancelled", "failed", "fallback", "preset", "blocked"})
READER_CLEANUP = frozenset({"not_observed", "not_required", "confirmed", "unconfirmed"})
_CREATION_LOCK = threading.Lock()


def _payload(state, requested, effective, *, failure=None, restart=False, outcome=None,
             handoff=False, cleanup="not_observed", outcomes=None, active=False):
    return dict(version=1, state=state, requested_mode=requested, effective_mode=effective,
                failure_code=failure, last_outcome=outcome, handoff_started=handoff,
                reader_cleanup=cleanup, segment_active=active,
                next_segment_allowed=requested is not None and not restart and not active and cleanup != "unconfirmed",
                restart_required=restart, outcomes=dict(outcomes) if outcomes is not None else
                {key: 0 for key in sorted(OUTCOMES)}, physical_playback_verified=False)


def configured_mode(connection):
    value = getattr(connection, "_longmemory_cosy_delivery_mode", "buffered")
    if not isinstance(value, str) or value not in MODES:
        raise ValueError("cosyvoice_delivery_mode_invalid")
    return value


class DeliverySession:
    def __init__(self, mode):
        self.mode = mode
        self.effective = mode
        self.failure = None
        self.blocked = False
        self.last_outcome = None
        self.handoff = False
        self.cleanup = "not_observed"
        self.active = False
        self.outcomes = {key: 0 for key in sorted(OUTCOMES)}
        self.lock = threading.Lock()

    def select(self, requested):
        with self.lock:
            if requested != self.mode:
                # 公共启动器通过重启切换。旧生产者不能在同连接内借用新配置身份。
                self.blocked, self.failure = True, "configuration_changed"
            elif not self.blocked and not self.active and self.cleanup == "unconfirmed":
                self.blocked, self.failure = True, "reader_cleanup_unconfirmed"
            return None if self.blocked else self.effective

    def degrade(self, reason, *, blocked=False):
        if reason not in FAILURES:
            raise ValueError("cosyvoice_delivery_failure_invalid")
        with self.lock:
            self.failure = reason
            self.blocked = self.blocked or blocked
            if self.mode != "buffered":
                # 仅降级后续片段；绝不重放已交付片段，也不写回用户的持久化选择。
                self.effective = "buffered"

    def begin(self):
        with self.lock:
            self.active, self.last_outcome, self.handoff = True, None, False
            self.cleanup = "not_required"

    def mark_handoff(self):
        with self.lock:
            self.handoff = True

    def reader_started(self):
        with self.lock:
            self.cleanup = "unconfirmed"

    def note(self, outcome, *, handoff=False, cleanup=None):
        if outcome not in OUTCOMES:
            raise ValueError("cosyvoice_delivery_outcome_invalid")
        if cleanup is not None and cleanup not in READER_CLEANUP:
            raise ValueError("cosyvoice_delivery_cleanup_invalid")
        with self.lock:
            self.outcomes[outcome] = min(1_000_000, self.outcomes[outcome] + 1)
            self.last_outcome, self.handoff = outcome, bool(handoff)
            self.active = False
            if cleanup is not None:
                self.cleanup = cleanup

    def snapshot(self, requested):
        with self.lock:
            mismatch = requested != self.mode
            blocked = self.blocked or mismatch
            return _payload("restart_required" if blocked else (
                "buffered_fallback" if self.mode != self.effective else "configured"),
                requested, None if blocked else self.effective,
                failure="configuration_changed" if mismatch else self.failure,
                restart=blocked, outcome=self.last_outcome, handoff=self.handoff,
                cleanup=self.cleanup, outcomes=self.outcomes, active=self.active)


def session_for(connection):
    mode = configured_mode(connection)
    with _CREATION_LOCK:
        session = getattr(connection, ATTRIBUTE, None)
        if session is None:
            session = DeliverySession(mode)
            setattr(connection, ATTRIBUTE, session)
        return session


def delivery_snapshot(connection=None):
    """只读元数据入口；不创建session、不读档案/缓存、不发HTTP、不改变降级决定。"""
    if connection is None:
        return _payload("no_connection", None, None)
    try:
        mode = configured_mode(connection)
    except ValueError:
        return _payload("invalid_configuration", None, None, restart=True)
    session = getattr(connection, ATTRIBUTE, None)
    if session is None:
        return _payload("not_observed", mode, mode)
    return session.snapshot(mode)
