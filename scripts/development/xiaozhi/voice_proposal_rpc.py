"""Python3.10语音侧的固定同机候选RPC；无宿主对象、学校key或正式prepare入口。

仅从LONGMEMORY_RUNTIME_URL/TOKEN派生同一authority的固定路由。每操作一次
HTTP请求，无重试/重定向/环境代理。客户端断开只关闭本地socket，不能确认上游
退出；原计算槽的CloseConfirmation只由匹配的宿主关闭ACK更新。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import math
import os
import re
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import UUID

from voice_preemptive import CloseConfirmation, TurnStamp


ROUTES = MappingProxyType({name: "/api/internal/memory/proposals/" + name
                          for name in ("snapshot", "start", "confirm", "cancel", "close")})
MAX_BODY = 262144
MAX_REQUEST = 192 * 1024


class ProposalRPCError(Exception):
    """只有固定脱敏代码；不包含地址、Token、正文、响应或原始异常。"""


def _hex(value, minimum=32, maximum=32):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d,%d}" % (minimum, maximum), value) is not None


def _messages(value):
    if (not isinstance(value, (tuple, list)) or not 1 <= len(value) <= 128
            or any(not isinstance(row, (tuple, list)) or len(row) != 2
                   or not isinstance(row[0], str) or row[0] not in {"system", "user", "assistant"}
                   or not isinstance(row[1], str) for row in value)
            or value[0][0] != "system" or any(row[0] == "system" for row in value[1:])
            or sum(len(row[1]) for row in value) > 32000):
        raise ProposalRPCError("proposal_rpc_messages_invalid")
    return [list(row) for row in value]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


@dataclass
class _Started:
    scope: TurnStamp
    snapshot_id: str = field(repr=False)
    confirmation: CloseConfirmation = field(repr=False)
    task: asyncio.Task | None = field(default=None, repr=False)
    confirming: asyncio.Task | None = field(default=None, repr=False)
    confirm_attempted: bool = False


class VoiceProposalRPC:
    """每连接一个客户端；共享计算名额仍由语音候选核心/宿主原网关负责。"""

    @classmethod
    def from_environment(cls, *, connection_id, environ=None,
                         timeout_seconds=2.0, cleanup_seconds=5.0):
        env = os.environ if environ is None else environ
        try:
            url = urlsplit(env.get("LONGMEMORY_RUNTIME_URL", ""))
            token = env.get("LONGMEMORY_RUNTIME_TOKEN", "")
            port = url.port
            if (url.scheme != "http" or url.hostname != "127.0.0.1"
                    or port is None or not 1 <= port <= 65535
                    or url.netloc != "127.0.0.1:" + str(port)
                    or url.path != "/api/internal/memory/prepare" or url.query or url.fragment
                    or url.username or url.password or not _hex(token, 64, 64)
                    or not _hex(connection_id)):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ProposalRPCError("proposal_rpc_authority_invalid") from None
        for value in (timeout_seconds, cleanup_seconds):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 10:
                raise ProposalRPCError("proposal_rpc_timeout_invalid")
        return cls(port, token, connection_id, timeout_seconds, cleanup_seconds)

    def __init__(self, port, token, connection_id, timeout_seconds, cleanup_seconds):
        if (type(port) is not int or not 1 <= port <= 65535 or not _hex(token, 64, 64)
                or not _hex(connection_id)):
            raise ProposalRPCError("proposal_rpc_authority_invalid")
        self._port, self._token = port, token
        self._connection_id = connection_id
        self._timeout, self._cleanup_timeout = timeout_seconds, cleanup_seconds
        self._loop = self._latest = self._active = None
        self._attempted_turn = -1
        self._closed = False
        self._writers = set()
        self._counts = dict.fromkeys(("requests", "failed", "timeouts", "cancelled", "stale",
                                    "acknowledged", "unconfirmed"), 0)

    @property
    def connection_id(self):
        return self._connection_id

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and loop is not self._loop:
            raise ProposalRPCError("proposal_rpc_event_loop_mismatch")
        self._loop = loop

    def _body(self, scope):
        if type(scope) is not TurnStamp or any(value >= 2**63 for value in (
                scope.turn_id, scope.transcript_revision, scope.cancel_epoch)):
            raise ProposalRPCError("proposal_rpc_scope_invalid")
        return {"version": 1, "connection_id": self.connection_id, "turn_id": scope.turn_id,
                "transcript_revision": scope.transcript_revision, "cancel_epoch": scope.cancel_epoch}

    def _advance(self, scope):
        self._check_loop()
        self._body(scope)
        if self._closed:
            raise ProposalRPCError("proposal_rpc_closed")
        previous = self._latest
        if (previous is not None and (scope.turn_id < previous.turn_id
                or scope.cancel_epoch < previous.cancel_epoch
                or (scope.turn_id == previous.turn_id and scope.transcript_revision < previous.transcript_revision))):
            self._counts["stale"] += 1
            raise ProposalRPCError("proposal_rpc_stale_scope")
        self._latest = scope

    async def _exchange(self, operation, body):
        # 固定路由从枚举取，不允许调用者提供URL/path。
        path = ROUTES[operation]
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        if len(payload) > MAX_REQUEST:
            raise ProposalRPCError("proposal_rpc_request_too_large")
        writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self._port, limit=8192)
            self._writers.add(writer)
            headers = ("POST " + path + " HTTP/1.1\r\nHost: 127.0.0.1:" + str(self._port)
                       + "\r\nAuthorization: Bearer " + self._token
                       + "\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                       + str(len(payload)) + "\r\n\r\n").encode("ascii")
            writer.write(headers + payload)
            await writer.drain()
            raw = await reader.readuntil(b"\r\n\r\n")
            if len(raw) > 8192:
                raise ValueError
            rows = raw.decode("ascii").split("\r\n")
            status = rows[0].split(" ", 2)
            if len(status) < 2 or status[0] not in {"HTTP/1.1", "HTTP/1.0"} or status[1] != "200":
                raise ProposalRPCError("proposal_rpc_rejected")
            response_headers = {}
            for row in rows[1:]:
                if not row:
                    continue
                key, value = row.split(":", 1)
                key = key.strip().lower()
                if key in response_headers:
                    raise ValueError
                response_headers[key] = value.strip()
            if ("transfer-encoding" in response_headers
                    or response_headers.get("content-type", "").split(";", 1)[0].strip() != "application/json"):
                raise ValueError
            size = int(response_headers["content-length"])
            if not 0 < size <= MAX_BODY:
                raise ValueError
            content = await reader.readexactly(size)
            result = json.loads(content, object_pairs_hook=_unique,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if (not isinstance(result, dict) or type(result.get("version")) is not int
                    or result["version"] != 1 or "error" in result):
                raise ValueError
            return result
        finally:
            if writer is not None:
                self._writers.discard(writer)
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), .25)
                except asyncio.CancelledError:
                    writer.transport.abort()
                    raise
                except Exception:
                    writer.transport.abort()

    async def _post(self, operation, body, *, cleanup=False):
        self._check_loop()
        if operation not in ROUTES:
            raise ProposalRPCError("proposal_rpc_operation_invalid")
        self._counts["requests"] += 1
        try:
            return await asyncio.wait_for(self._exchange(operation, body),
                                          self._cleanup_timeout if cleanup else self._timeout)
        except asyncio.CancelledError:
            self._counts["cancelled"] += 1
            raise
        except asyncio.TimeoutError:
            self._counts["timeouts"] += 1
            raise ProposalRPCError("proposal_rpc_timeout") from None
        except Exception:
            self._counts["failed"] += 1
            raise ProposalRPCError("proposal_rpc_unavailable") from None

    async def snapshot(self, *, scope, query, session_id):
        self._advance(scope)
        if (not isinstance(query, str) or not query.strip() or len(query) > 16000
                or not _hex(session_id)):
            raise ProposalRPCError("proposal_rpc_snapshot_invalid")
        result = await self._post("snapshot", dict(self._body(scope), query=query, session_id=session_id))
        self._dto(result, {"version", "state", "snapshot_id", "memory_context", "reason_code"},
                  {"ready", "unavailable"})
        if (result["state"] == "ready" and (not _hex(result["snapshot_id"])
                or not isinstance(result["memory_context"], str) or len(result["memory_context"]) > 32000)):
            raise ProposalRPCError("proposal_rpc_snapshot_invalid")
        if (result["state"] == "unavailable" and (result["snapshot_id"] is not None
                or result["memory_context"] is not None)):
            raise ProposalRPCError("proposal_rpc_snapshot_invalid")
        if self._latest != scope:
            return {"version": 1, "state": "unavailable", "snapshot_id": None,
                    "memory_context": None, "reason_code": "stale"}
        return result

    async def start(self, *, scope, snapshot_id, messages, tools_required=False, close_confirmation=None):
        self._advance(scope)
        if (not _hex(snapshot_id) or type(tools_required) is not bool
                or self._active is not None or self._attempted_turn == scope.turn_id):
            raise ProposalRPCError("proposal_rpc_start_not_admitted")
        messages = _messages(messages)
        confirmation = close_confirmation or CloseConfirmation()
        if type(confirmation) is not CloseConfirmation:
            raise ProposalRPCError("proposal_rpc_close_confirmation_invalid")
        confirmation.required = True
        record = _Started(scope, snapshot_id, confirmation, task=asyncio.current_task())
        self._active, self._attempted_turn = record, scope.turn_id
        try:
            result = await self._post("start", dict(self._body(scope), snapshot_id=snapshot_id,
                                                    messages=messages, tools_required=tools_required))
        finally:
            record.task = None
        self._dto(result, {"version", "state", "reason_code"}, {"preparing", "miss"})
        if self._active is not record or self._latest != scope:
            return {"version": 1, "state": "miss", "reason_code": "stale"}
        return result

    async def confirm(self, *, scope, snapshot_id, query, messages, formal_turn_id,
                      client_round_id, session_id, tools_required=False):
        self._advance(scope)
        record = self._active
        if record is None or record.scope != scope or record.confirm_attempted:
            return {"version": 1, "state": "miss", "text": None, "reason_code": "no_candidate"}
        if (not _hex(snapshot_id) or snapshot_id != record.snapshot_id or type(tools_required) is not bool
                or not isinstance(query, str) or not query.strip() or len(query) > 16000
                or not isinstance(formal_turn_id, str) or not 1 <= len(formal_turn_id) <= 64
                or not _hex(client_round_id, 24, 32) or not _hex(session_id)):
            raise ProposalRPCError("proposal_rpc_confirmation_invalid")
        try:
            if str(UUID(formal_turn_id)) != formal_turn_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ProposalRPCError("proposal_rpc_confirmation_invalid") from None
        record.confirming = asyncio.current_task()
        record.confirm_attempted = True
        try:
            result = await self._post("confirm", dict(self._body(scope), snapshot_id=snapshot_id, query=query,
                messages=_messages(messages), tools_required=tools_required, formal_turn_id=formal_turn_id,
                client_round_id=client_round_id, session_id=session_id))
        finally:
            record.confirming = None
        if self._active is not record or self._latest != scope:
            self._counts["stale"] += 1
            return {"version": 1, "state": "miss", "text": None, "reason_code": "stale"}
        self._dto(result, {"version", "state", "text", "reason_code"}, {"adopted", "miss"})
        if result["state"] == "adopted":
            answer = result["text"]
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 8192:
                raise ProposalRPCError("proposal_rpc_answer_invalid")
        elif result["text"] is not None:
            raise ProposalRPCError("proposal_rpc_answer_on_miss")
        return result

    @staticmethod
    def _dto(result, keys, states):
        if (set(result) != keys or not isinstance(result.get("state"), str) or result["state"] not in states
                or ("reason_code" in result and result["reason_code"] is not None
                    and (not isinstance(result["reason_code"], str)
                         or re.fullmatch(r"[a-z0-9_]{1,128}", result["reason_code"]) is None))):
            raise ProposalRPCError("proposal_rpc_response_invalid")

    def _close_dto(self, ack, operation):
        # 外部DTO的请求归属由本次固定路由/鉴权交换绑定；AF request_id在宿主内核验。
        self._dto(ack, {"version", "state", "owned_upstream_exited", "provider_compute_stopped"},
                  {"cancelled", "closing"} if operation == "cancel" else {"closed", "closing"})
        if (type(ack["owned_upstream_exited"]) is not bool or ack["provider_compute_stopped"] is not False
                or ((ack["state"] == "closing") == ack["owned_upstream_exited"])):
            raise ProposalRPCError("proposal_rpc_close_unconfirmed")
        if not ack["owned_upstream_exited"]:
            self._counts["unconfirmed"] += 1
            return False
        return True

    def _ack(self, record, ack, operation):
        if not self._close_dto(ack, operation):
            return False
        record.confirmation.confirmed = True
        if self._active is record:
            self._active = None
        self._counts["acknowledged"] += 1
        return True

    async def cancel(self, *, scope):
        self._check_loop()
        record = self._active
        if record is None or not self._cleanup_scope(scope, record):
            raise ProposalRPCError("proposal_rpc_cancel_scope_invalid")
        self._cancel_reads(record)
        result = await self._post("cancel", self._body(scope), cleanup=True)
        self._ack(record, result, "cancel")
        return result

    async def close(self, *, scope):
        self._check_loop()
        record = self._active
        if record is not None and not self._cleanup_scope(scope, record, closing=True):
            raise ProposalRPCError("proposal_rpc_close_scope_invalid")
        if record is not None:
            self._cancel_reads(record)
        result = await self._post("close", self._body(scope), cleanup=True)
        if record is not None:
            self._ack(record, result, "close")
        else:
            self._close_dto(result, "close")
        self._closed = result["state"] == "closed" and result["owned_upstream_exited"] is True
        return result

    @staticmethod
    def _cancel_reads(record):
        for task in (record.task, record.confirming):
            if task is not None and task is not asyncio.current_task() and not task.done():
                task.cancel()

    def _cleanup_scope(self, scope, record, *, closing=False):
        self._body(scope)
        if ((scope.turn_id < record.scope.turn_id if closing else scope.turn_id != record.scope.turn_id)
                or scope.cancel_epoch < record.scope.cancel_epoch
                or (scope.turn_id == record.scope.turn_id
                    and scope.transcript_revision < record.scope.transcript_revision)):
            return False
        if (self._latest is None or (scope.turn_id == self._latest.turn_id
                and scope.cancel_epoch >= self._latest.cancel_epoch
                and scope.transcript_revision >= self._latest.transcript_revision)):
            self._latest = scope
        return True

    async def aclose(self):
        self._check_loop()
        try:
            scope = self._latest if self._latest is not None else (self._active.scope if self._active else None)
            if not self._closed and scope is not None:
                await self.close(scope=scope)
            elif scope is None:
                self._closed = True
        except (ProposalRPCError, asyncio.CancelledError):
            return False
        finally:
            for writer in tuple(self._writers):
                writer.close()
        return self._active is None and self._closed

    def snapshot_status(self):
        return {"version": 1, "closed": self._closed, "active": int(self._active is not None),
                "local_sockets": len(self._writers), **self._counts}
