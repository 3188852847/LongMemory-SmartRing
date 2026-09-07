"""主动交流状态账本用例；只记录事实，不负责触发、生成或投递。"""

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from longmemory.core.proactive import (
    OutreachEvent,
    OutreachEvidence,
    OutreachState,
    OutreachTrigger,
    ProactiveOutreach,
    ProactiveOutreachStore,
    transition_outreach,
)


EVIDENCE_FOR_STATE = {
    OutreachState.BLOCKED: frozenset({OutreachEvidence.POLICY_DECISION}),
    OutreachState.QUEUED: frozenset({OutreachEvidence.SERVER_QUEUE}),
    OutreachState.TRANSPORT_SENT: frozenset({OutreachEvidence.TRANSPORT_WRITE}),
    OutreachState.DEVICE_ACKNOWLEDGED: frozenset({OutreachEvidence.DEVICE_ACK}),
    OutreachState.PLAYED: frozenset({
        OutreachEvidence.DEVICE_ACK, OutreachEvidence.USER_OBSERVED,
    }),
    OutreachState.EXPIRED: frozenset({
        OutreachEvidence.POLICY_DECISION, OutreachEvidence.SYSTEM_RECOVERY,
    }),
    OutreachState.CANCELLED: frozenset({OutreachEvidence.POLICY_DECISION}),
    OutreachState.FAILED: frozenset({
        OutreachEvidence.SERVER_QUEUE,
        OutreachEvidence.TRANSPORT_WRITE,
        OutreachEvidence.DEVICE_ACK,
        OutreachEvidence.SYSTEM_RECOVERY,
    }),
}


class ProactiveOutreachLedger:
    def __init__(
        self,
        store: ProactiveOutreachStore,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    def get(self, outreach_id: str) -> ProactiveOutreach | None:
        """读取当前投影，供编排器在产生外部副作用前核对状态。"""

        return self._store.get(outreach_id)

    def list_events(self, outreach_id: str) -> tuple[OutreachEvent, ...]:
        """读取只追加历史，避免应用测试依赖账本的私有存储字段。"""

        return self._store.list_events(outreach_id)

    def get_by_idempotency(
        self, subject_id: str, idempotency_key: str,
    ) -> ProactiveOutreach | None:
        """重复外部请求只读取第一次结果，不再次产生副作用。"""

        return self._store.get_by_idempotency(subject_id, idempotency_key)

    def create_candidate(
        self,
        *,
        subject_id: str,
        trigger: OutreachTrigger,
        trigger_reason_code: str,
        content: str,
        scheduled_for: datetime,
        expires_at: datetime,
        idempotency_key: str,
        policy_version: str | None = None,
    ) -> ProactiveOutreach:
        now = self._clock()
        outreach = ProactiveOutreach(
            id=self._id_factory(),
            subject_id=subject_id,
            trigger=trigger,
            trigger_reason_code=trigger_reason_code,
            content=content,
            created_at=now,
            scheduled_for=scheduled_for,
            expires_at=expires_at,
            state_changed_at=now,
            idempotency_key=idempotency_key,
            policy_version=policy_version,
        )
        event = OutreachEvent(
            id=self._id_factory(),
            outreach_id=outreach.id,
            sequence=1,
            previous_state=None,
            new_state=OutreachState.CANDIDATE,
            reason_code=trigger_reason_code,
            evidence=OutreachEvidence.SYSTEM_CREATED,
            occurred_at=now,
        )
        self._store.create(outreach, event)
        return outreach

    def record_transition(
        self,
        outreach_id: str,
        *,
        expected_revision: int,
        new_state: OutreachState,
        reason_code: str,
        evidence: OutreachEvidence,
        failure_reason: str | None = None,
    ) -> ProactiveOutreach:
        if evidence not in EVIDENCE_FOR_STATE.get(new_state, frozenset()):
            raise ValueError("outreach_evidence_does_not_support_state")
        current = self._store.get(outreach_id)
        if current is None:
            raise ValueError("outreach_not_found")
        if current.revision != expected_revision:
            raise ValueError("outreach_transition_conflict")
        occurred_at = self._clock()
        changed = transition_outreach(
            current,
            new_state=new_state,
            occurred_at=occurred_at,
            failure_reason=failure_reason,
        )
        event = OutreachEvent(
            id=self._id_factory(),
            outreach_id=outreach_id,
            sequence=changed.revision,
            previous_state=current.state,
            new_state=new_state,
            reason_code=reason_code,
            evidence=evidence,
            occurred_at=occurred_at,
        )
        self._store.transition(changed, event, expected_revision=expected_revision)
        return changed
