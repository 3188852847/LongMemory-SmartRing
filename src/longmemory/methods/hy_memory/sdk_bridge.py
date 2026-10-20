"""固定 SDK 的低层边界；U 方法/管理适配位于独立 method 模块。"""

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Protocol
from dataclasses import replace


SDK_VERSION = "2.0.3"
SOURCE_COMMIT = "2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed"
SOURCE_NAMESPACE = "smartring_synthetic"


class HyResponseError(RuntimeError):
    """响应失败或与锁定 SDK 结构不符；不携带外部原文/密钥。"""


class HyClient(Protocol):
    def add(self, data: list[dict], **kwargs: Any) -> dict: ...
    def search(self, query: str, **kwargs: Any) -> dict: ...
    def get_user_profile(self, *, user_id: str) -> dict: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class HyItem:
    memory_id: str
    content: str
    channel: str
    layer: str | None
    sdk_score: float | None
    # 仅从独立透传的 meta 读取来源；不从正文/metadata 猜测证据。
    source_event_ids: tuple[str, ...] | None
    visible_memory_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class HyRecall:
    request_id: str
    items: tuple[HyItem, ...]
    profile: HyItem | None
    elapsed_ms: float | None


@dataclass(frozen=True)
class HyWrite:
    request_id: str
    raw_memory_id: str
    derived_memory_ids: tuple[str, ...]
    elapsed_ms: float | None


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HyResponseError("hy_invalid_response")
    return value


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise HyResponseError("hy_invalid_response")
    return float(value)


def _elapsed(value: Any) -> float | None:
    value = _number(value)
    if value is not None and value < 0:
        raise HyResponseError("hy_invalid_response")
    return value


def _sources(meta: Any) -> tuple[str, ...] | None:
    if meta is None:
        return None
    if not isinstance(meta, list):
        raise HyResponseError("hy_invalid_meta")
    ids = []
    for entry in meta:
        if not isinstance(entry, dict):
            raise HyResponseError("hy_invalid_meta")
        if entry.get("namespace") != SOURCE_NAMESPACE:
            continue
        source_ids = entry.get("source_event_ids")
        if not isinstance(source_ids, list) or not source_ids:
            raise HyResponseError("hy_invalid_meta")
        ids.extend(_text(value) for value in source_ids)
    return tuple(dict.fromkeys(ids)) if ids else None


def _item(row: Any, channel: str) -> HyItem:
    if not isinstance(row, dict):
        raise HyResponseError("hy_invalid_response")
    layer = row.get("layer")
    if layer is not None:
        layer = _text(layer)
    memory_id = _text(row.get("memory_id"))
    chain = row.get("evolution_chain")
    visible = [memory_id]
    evidence = row.get("evidence_memory_ids")
    if evidence is not None:
        if not isinstance(evidence, list) or len(evidence) > 16:
            raise HyResponseError("hy_invalid_schema_evidence")
        visible.extend(_text(value) for value in evidence)
    if chain is not None:
        if not isinstance(chain, list) or len(chain) > 1000:
            raise HyResponseError("hy_invalid_evolution_chain")
        for version in chain:
            if not isinstance(version, dict):
                raise HyResponseError("hy_invalid_evolution_chain")
            visible.append(_text(version.get("node_id")))
    return HyItem(memory_id, _text(row.get("content")), channel,
                  layer, _number(row.get("score")), _sources(row.get("meta")), tuple(dict.fromkeys(visible)))


def normalize_search(response: Any, profile_response: Any = None) -> HyRecall:
    if not isinstance(response, dict) or response.get("success") is False:
        raise HyResponseError("hy_search_failed")
    channels = response.get("memories")
    # 2.0.3 为 schema/normal/proactive；README 中 profile 说法不作为协议。
    if not isinstance(channels, dict) or set(channels) != {"schema", "normal", "proactive"}:
        raise HyResponseError("hy_invalid_channels")
    items = []
    for channel in ("normal", "schema", "proactive"):
        rows = channels[channel]
        if not isinstance(rows, list):
            raise HyResponseError("hy_invalid_response")
        items.extend(_item(row, channel) for row in rows)
    profile = None
    if profile_response is not None:
        if not isinstance(profile_response, dict) or "profile" not in profile_response:
            raise HyResponseError("hy_invalid_profile")
        if profile_response["profile"] is not None:
            profile = _item(profile_response["profile"], "profile")
            if "basic_info" in profile_response["profile"]:
                profile=replace(profile,content="[当前用户画像；不证明任意历史日期的状态]\n"+profile.content)
    return HyRecall(_text(response.get("request_id")), tuple(items), profile,
                    _elapsed(response.get("elapsed_ms")))


class HySdkBridge:
    """只接受调用方显式注入的 client；构造不导入 SDK、不读环境、不联网。

    request_id 用于追踪，不能当作 SDK 幂等保证。发生异常/失败后 SDK
    可能已经部分写入；这里不重试、不回滚，也不声称 source_only 已可靠保存。
    """

    def __init__(self, client: HyClient, *, user_id: str, agent_id: str = "v_synthetic"):
        self._client = client
        self.user_id = _text(user_id)
        self.agent_id = _text(agent_id)
        self._closed = False

    def _check_open(self):
        if self._closed:
            raise RuntimeError("hy_bridge_closed")

    def add_event(self, *, event_id: str, role: str, content: str,
                  occurred_at: datetime, session_id: str) -> HyWrite:
        self._check_open()
        event_id, content, session_id = _text(event_id), _text(content), _text(session_id)
        if role not in {"user", "assistant"}:
            raise ValueError("hy_unsupported_role")
        if not isinstance(occurred_at, datetime) or occurred_at.utcoffset() is None:
            raise ValueError("hy_timestamp_requires_timezone")
        # 保留助手角色以检测错误归因；不把建议改写成用户事实。
        try:
            result = self._client.add(
                [{"role": role, "content": content}], user_id=self.user_id,
                agent_id=self.agent_id, session_id=session_id, source=SOURCE_NAMESPACE,
                scene="chat", memory_at=occurred_at, request_id=event_id,
                meta={"namespace": SOURCE_NAMESPACE, "source_event_ids": [event_id],
                      "occurred_at": occurred_at.isoformat(), "role": role},
            )
        except Exception:
            raise HyResponseError("hy_add_transport_failed_state_unknown") from None
        if not isinstance(result, dict) or result.get("success") is not True:
            raise HyResponseError("hy_add_failed_state_unknown")
        derived = result.get("memory_ids", [])
        if not isinstance(derived, list):
            raise HyResponseError("hy_invalid_response_state_unknown")
        return HyWrite(_text(result.get("request_id")), _text(result.get("memory_id")),
                       tuple(_text(value) for value in derived), _elapsed(result.get("elapsed_ms")))

    def search(self, query: str, *, limit: int = 5, include_profile: bool = False) -> HyRecall:
        self._check_open()
        query = _text(query)
        if type(limit) is not int or not 1 <= limit <= 100 or type(include_profile) is not bool:
            raise ValueError("hy_invalid_search_options")
        try:
            response = self._client.search(
                query, scene="chat", search_mode="default", user_ids=[self.user_id],
                agent_ids=[self.agent_id], include_sources=[SOURCE_NAMESPACE], limit=limit,
                schema_limit=0, intention_limit=0,
            )
            # Profile API 仅按 user 隔离，不支持 agent/source 过滤；需独占合成 user。
            profile = self._client.get_user_profile(user_id=self.user_id) if include_profile else None
        except Exception:
            raise HyResponseError("hy_search_transport_failed") from None
        return normalize_search(response, profile)

    def close(self) -> None:
        if not self._closed:
            self._client.close()
            self._closed = True
