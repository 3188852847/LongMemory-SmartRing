"""主动交流的运行期执行边界。

本模块只负责把已保存策略、设备实时状态和不可变外联账本组合成一次执行结果。
配置编辑与候选学习分别属于其他协作者，避免诊断投递反向依赖记忆 CRUD。
"""

from longmemory.adapters.device_control import (
    XiaozhiProactiveDelivery,
    XiaozhiRuntimeStateProbe,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_proactive_runtime_state import (
    SQLiteProactiveHistoryReader,
)
from longmemory.application.proactive import (
    ProactiveOutreachDispatcher,
    ProactiveOutreachLedger,
)
from longmemory.core.proactive import OutreachPolicyState, OutreachTrigger

from .errors import MemoryAccessError
from .proactive_presenters import outreach_result_json


class ProactiveRuntimeBackend:
    """执行主动交流动作；所有持久化仍经过显式能力受限的数据库入口。"""

    def __init__(self, *, open_database, clock):
        self._open_database = open_database
        self._clock = clock

    async def manual_test(self, request, client):
        """执行一次用户明确发起的短文本测试；同 request_id 绝不重播。"""

        subject_id = "user:self"
        idempotency_key = "manual-console:" + request.request_id
        with self._open_database() as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection, commit_changes=False),
                clock=self._clock,
            )
            existing = ledger.get_by_idempotency(subject_id, idempotency_key)
            if existing is not None:
                return outreach_result_json(existing, replayed=True)
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)

        device = await XiaozhiRuntimeStateProbe(client).probe()
        now = self._clock()
        with self._open_database(write_capability="proactive") as connection:
            ledger = ProactiveOutreachLedger(
                SQLiteProactiveOutreachStore(connection), clock=lambda: now,
            )
            existing = ledger.get_by_idempotency(subject_id, idempotency_key)
            if existing is not None:
                return outreach_result_json(
                    existing, replayed=True, device=device,
                )
            settings = SQLiteProactivePolicyStore(connection).get(subject_id)
            if settings.revision != request.expected_policy_revision:
                raise MemoryAccessError("proactive_settings_conflict", 409)
            runtime = SQLiteProactiveHistoryReader(connection).read(
                subject_id, now=now,
            )
            runtime = OutreachPolicyState(
                attempted_at=runtime.attempted_at,
                # 所有者显式点击属于诊断动作，不是系统自主追问；其余许可、
                # 时段、频率、勿扰和设备会话门控仍保持。
                awaiting_user_response=False,
                user_session_active=device.user_session_active,
                quiet_until=settings.quiet_until,
            )
            try:
                outreach = ledger.create_candidate(
                    subject_id=subject_id,
                    trigger=OutreachTrigger.MANUAL_TEST,
                    trigger_reason_code="manual_console_test",
                    content=request.text,
                    scheduled_for=now,
                    expires_at=now + settings.config.maximum_lifetime,
                    idempotency_key=idempotency_key,
                    policy_version=settings.config.policy_version,
                )
                result = await ProactiveOutreachDispatcher(
                    ledger,
                    delivery_queue=XiaozhiProactiveDelivery(client).queue,
                    clock=lambda: now,
                ).dispatch(
                    outreach.id,
                    expected_revision=outreach.revision,
                    settings=settings,
                    runtime_state=runtime,
                )
            except ValueError:
                raise MemoryAccessError(
                    "proactive_dispatch_conflict", 409,
                ) from None
            return outreach_result_json(
                result.outreach,
                replayed=False,
                decision=result.decision,
                delivery=result.delivery,
                device=device,
            )
