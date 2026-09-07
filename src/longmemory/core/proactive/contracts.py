"""主动交流账本的存储边界。"""

from typing import Protocol

from .models import OutreachEvent, ProactiveOutreach


class ProactiveOutreachStore(Protocol):
    def create(self, outreach: ProactiveOutreach, event: OutreachEvent) -> None: ...

    def transition(
        self,
        outreach: ProactiveOutreach,
        event: OutreachEvent,
        *,
        expected_revision: int,
    ) -> None: ...

    def get(self, outreach_id: str) -> ProactiveOutreach | None: ...

    def get_by_idempotency(
        self, subject_id: str, idempotency_key: str,
    ) -> ProactiveOutreach | None: ...

    def list_recent(
        self, subject_id: str, *, limit: int = 20,
    ) -> tuple[ProactiveOutreach, ...]: ...

    def list_events(self, outreach_id: str) -> tuple[OutreachEvent, ...]: ...
