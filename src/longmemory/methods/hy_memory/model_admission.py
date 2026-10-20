"""单上游槽的有界优先FIFO；排队不占预算，不抢占已在飞的正式/后台请求。"""

from collections import deque
from contextlib import contextmanager
from threading import Condition, Lock
from time import perf_counter


KINDS = ('answer', 'required_hy', 'candidate', 'background')
QUEUE_LIMITS = {'answer': 32, 'required_hy': 32, 'candidate': 1, 'background': 1}


class AdmissionClosed(RuntimeError):
    pass


class AdmissionFull(RuntimeError):
    pass


def work_kind(phase, work_class=None):
    if work_class is not None and not isinstance(work_class, str):
        raise ValueError('model_work_class_invalid')
    if work_class == 'background':
        if phase != 'hy': raise ValueError('model_background_phase_invalid')
        return 'background'
    # 未知或缺少标记保守保留前台；不能靠模型body/消息推断后台。
    return 'answer' if phase == 'answer' else 'required_hy'


class _Ticket:
    def __init__(self, owner, kind, preempt):
        self.owner, self.kind, self.preempt = owner, kind, preempt
        self.enqueued = self.last = perf_counter()
        self.waits = dict.fromkeys((*KINDS, 'queue_or_external'), 0.)
        self.cancelled = self.granted = self.released = self.preempt_requested = False
        self.quarantined = False
        self.model_queue_ms = None

    def try_acquire(self):
        return self.owner.try_acquire(self)

    def cancel(self):
        return self.owner.cancel(self)

    def release(self):
        return self.owner.release(self)

    def metadata(self):
        return {'admission_class': self.kind, 'model_queue_ms': self.model_queue_ms,
                'model_queue_by_active_ms': {kind: round(value, 3) for kind, value in self.waits.items()}}


class ModelAdmission:
    def __init__(self, slot, *, limits=None):
        self._slot = slot
        self._condition = Condition(Lock())
        self._queues = {kind: deque() for kind in KINDS}
        self._limits = dict(QUEUE_LIMITS if limits is None else limits)
        if (set(self._limits) != set(KINDS)
                or any(type(value) is not int or value < 1 for value in self._limits.values())):
            raise ValueError('model_admission_limits_invalid')
        self._active = None
        self._closed = False

    def _account(self):
        now = perf_counter()
        blocker = self._active.kind if self._active is not None else 'queue_or_external'
        for queue in self._queues.values():
            for ticket in queue:
                ticket.waits[blocker] += max(0., now-ticket.last)*1000
                ticket.last = now
        return now

    def enqueue(self, kind, *, preempt=None):
        if kind not in KINDS: raise ValueError('model_admission_class_invalid')
        callback = None
        with self._condition:
            if self._closed: raise AdmissionClosed('model_admission_closed')
            queue = self._queues[kind]
            if len(queue) >= self._limits[kind]: raise AdmissionFull('model_admission_full')
            ticket = _Ticket(self, kind, preempt)
            queue.append(ticket)
            active = self._active
            if (kind in ('answer', 'required_hy') and active is not None
                    and active.kind == 'candidate' and not active.preempt_requested):
                active.preempt_requested = True
                callback = active.preempt
                if callback is None: active.quarantined = True
            self._condition.notify_all()
        # 不持调度锁调用取消：候选关闭/归还槽位也会取此锁。
        if callback is not None:
            try: callback()
            except Exception:
                with self._condition:
                    if self._active is active: active.quarantined = True
        return ticket

    def try_acquire(self, ticket):
        with self._condition:
            if self._closed: raise AdmissionClosed('model_admission_closed')
            if ticket.cancelled: raise AdmissionClosed('model_admission_cancelled')
            if ticket.released: raise AdmissionClosed('model_admission_released')
            if ticket.granted: return ticket
            first = next((queue[0] for queue in self._queues.values() if queue), None)
            if self._active is not None or first is not ticket: return None
            if not self._slot.acquire(blocking=False): return None
            now = self._account()
            self._queues[ticket.kind].popleft()
            ticket.granted = True
            ticket.model_queue_ms = round(max(0., now-ticket.enqueued)*1000, 3)
            self._active = ticket
            return ticket

    def cancel(self, ticket):
        with self._condition:
            if ticket.granted: return False  # 活动候选须由原句柄完成关闭ACK再release。
            if not ticket.cancelled:
                self._account()
                try: self._queues[ticket.kind].remove(ticket)
                except ValueError: pass
                ticket.cancelled = True
            self._condition.notify_all()
            return True

    def release(self, ticket, *, acknowledged=False):
        with self._condition:
            if ticket.released: return True
            if self._active is not ticket: raise ValueError('model_admission_owner_mismatch')
            if ticket.preempt_requested and not acknowledged: return False
            self._account()
            self._active = None
            ticket.released = True
            self._slot.release()
            self._condition.notify_all()
            return True

    def quarantine(self, ticket):
        with self._condition:
            if self._active is ticket: ticket.quarantined = True
            self._condition.notify_all()

    @contextmanager
    def acquire(self, kind):
        ticket = self.enqueue(kind)
        try:
            while ticket.try_acquire() is None:
                with self._condition:
                    if self._closed: raise AdmissionClosed('model_admission_closed')
                    self._condition.wait(timeout=.01)
            yield ticket
        finally:
            if ticket.granted: self.release(ticket)
            else: ticket.cancel()

    def background_readiness(self):
        with self._condition:
            waiting = any(self._queues[kind] for kind in KINDS)
            reason = ('closed' if self._closed else 'requests_waiting' if waiting else
                      'model_busy' if self._active is not None or self._slot.locked() else None)
            return {'version': 1, 'eligible': reason is None, 'reason_code': reason}

    def snapshot(self):
        with self._condition:
            return {'closed': self._closed, 'active_class': self._active.kind if self._active else None,
                    'quarantined': bool(self._active and self._active.quarantined),
                    'waiting': {kind: len(queue) for kind, queue in self._queues.items()}}

    def close(self):
        with self._condition:
            self._account()
            self._closed = True
            self._condition.notify_all()
