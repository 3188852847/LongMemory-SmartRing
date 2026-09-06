"""把候选、许可策略、事件账本与受限投递端口连接起来。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from longmemory.core.proactive import (
    OutreachEvidence,
    OutreachPolicyAction,
    OutreachPolicyDecision,
    OutreachPolicyReason,
    OutreachPolicyState,
    OutreachState,
    ProactiveOutreach,
    ProactivePolicySettings,
    decide_outreach,
)

from .ledger import ProactiveOutreachLedger


class DeliveryQueueStatus(StrEnum):
    """当前适配层只承认服务端排队，不推测设备侧结果。"""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DeliveryQueueResult:
    status: DeliveryQueueStatus
    reason_code: str

    def __post_init__(self) -> None:
        if (self.reason_code != self.reason_code.strip()
                or not 1 <= len(self.reason_code) <= 120):
            raise ValueError("delivery_reason_code_invalid")


DeliveryQueue = Callable[[str, datetime], Awaitable[DeliveryQueueResult]]


@dataclass(frozen=True, slots=True)
class OutreachDispatchResult:
    """一次确定性执行结果；outreach 是本次结束后的真实账本投影。"""

    decision: OutreachPolicyDecision
    outreach: ProactiveOutreach
    delivery: DeliveryQueueResult | None = None


class ProactiveOutreachDispatcher:
    """执行一个已持久化候选，不创建内容、不重试也不运行定时器。"""

    def __init__(
        self,
        ledger: ProactiveOutreachLedger,
        *,
        delivery_queue: DeliveryQueue,
        clock: Callable[[], datetime],
    ) -> None:
        self._ledger = ledger
        self._delivery_queue = delivery_queue
        self._clock = clock

    async def dispatch(
        self,
        outreach_id: str,
        *,
        expected_revision: int,
        settings: ProactivePolicySettings,
        runtime_state: OutreachPolicyState = OutreachPolicyState(),
    ) -> OutreachDispatchResult:
        """评估并执行一次；先占有账本状态，再产生外部投递副作用。

        先把允许的候选推进到 ``queued``，可阻止两个执行者同时向设备
        投递同一条内容。设备适配器若只返回排队成功，账本也只停在 queued；
        后续状态必须由更强的真实证据推进。
        """

        outreach = self._ledger.get(outreach_id)
        if outreach is None:
            raise ValueError("outreach_not_found")
        if outreach.revision != expected_revision:
            raise ValueError("outreach_dispatch_conflict")
        if outreach.state != OutreachState.CANDIDATE:
            raise ValueError("outreach_not_candidate")
        if outreach.subject_id != settings.subject_id:
            raise ValueError("outreach_settings_subject_mismatch")

        now = self._clock()
        policy_state = replace(runtime_state, quiet_until=settings.quiet_until)
        decision = decide_outreach(
            outreach,
            now=now,
            state=policy_state,
            config=settings.config,
        )
        if decision.action == OutreachPolicyAction.WAIT:
            return OutreachDispatchResult(decision, outreach)
        if decision.action == OutreachPolicyAction.BLOCK:
            target = (
                OutreachState.EXPIRED
                if decision.reason == OutreachPolicyReason.EXPIRED
                else OutreachState.BLOCKED
            )
            changed = self._ledger.record_transition(
                outreach.id,
                expected_revision=outreach.revision,
                new_state=target,
                reason_code=decision.reason.value,
                evidence=OutreachEvidence.POLICY_DECISION,
            )
            return OutreachDispatchResult(decision, changed)

        queued = self._ledger.record_transition(
            outreach.id,
            expected_revision=outreach.revision,
            new_state=OutreachState.QUEUED,
            reason_code=decision.reason.value,
            evidence=OutreachEvidence.SERVER_QUEUE,
        )
        try:
            delivery = await self._delivery_queue(queued.content, queued.expires_at)
            if not isinstance(delivery, DeliveryQueueResult):
                raise TypeError("delivery_queue_result_invalid")
        except Exception:
            # 不把第三方异常正文持久化，避免日志或数据库意外保存敏感内容。
            failed = self._ledger.record_transition(
                queued.id,
                expected_revision=queued.revision,
                new_state=OutreachState.FAILED,
                reason_code="delivery_exception",
                evidence=OutreachEvidence.SERVER_QUEUE,
                failure_reason="delivery_exception",
            )
            return OutreachDispatchResult(decision, failed)

        if delivery.status == DeliveryQueueStatus.REJECTED:
            failed = self._ledger.record_transition(
                queued.id,
                expected_revision=queued.revision,
                new_state=OutreachState.FAILED,
                reason_code=delivery.reason_code,
                evidence=OutreachEvidence.SERVER_QUEUE,
                failure_reason=delivery.reason_code,
            )
            return OutreachDispatchResult(decision, failed, delivery)
        return OutreachDispatchResult(decision, queued, delivery)
