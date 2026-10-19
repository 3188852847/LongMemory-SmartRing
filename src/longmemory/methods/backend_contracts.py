"""应用后端装配与管理契约；不要求 SQLite、原子事实或 L0–L3。"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from .contracts import MemoryEvent, MemoryMethod, UnsupportedCapabilityError


@dataclass(frozen=True, slots=True)
class StateResource:
    """一个后端可拥有多个文件或目录；路径只由可信装配者指定。"""

    name: str
    path: Path
    kind: Literal["file", "directory"]


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """方法自己的可管理条目，可以是摘要、块、图节点或事实。

    source_event_ids=None 表示无法提供来源，不等于没有来源。
    时间未知时为 None；不把记录时间伪装成事实生效时间。
    revision 由适配器提供并在写操作时原子比较；不是鉴权凭据。
    """

    item_id: str
    content: str
    revision: str
    kind: str
    source_event_ids: tuple[str, ...] | None = None
    recorded_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    state: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryPage:
    items: tuple[MemoryItem, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class ManagementCapabilities:
    listing: bool = False
    detail: bool = False
    correction: bool = False
    deletion: bool = False
    temporal_history: bool = False
    scenarios: bool = False
    personas: bool = False


class MemoryAdministration(Protocol):
    capabilities: ManagementCapabilities

    def list_items(self, *, query: str = "", state: str = "active",
                   limit: int = 25, offset: int = 0) -> MemoryPage: ...

    def get_item(self, item_id: str) -> MemoryItem: ...

    def correct_item(self, item_id: str, content: str, *,
                     expected_revision: str, source: MemoryEvent) -> MemoryItem:
        """source 为用户明确纠错的来源；失败不得假称已纠正。"""
        ...

    def delete_item(self, item_id: str, *, expected_revision: str) -> None:
        """只删除引擎条目，平台来源保留；不是隐私全量擦除。"""
        ...


@dataclass(frozen=True, slots=True)
class BackendAssembly:
    """一个显式选定的引擎及管理适配；Runtime 拥有 method 的关闭责任。

    新后端默认不接旧派生功能。legacy_sqlite 仅限本仓库旧引擎适配器；
    外部方法不能通过这个标志把私有结构写进通用协议。
    management=None 必须公开不支持，不能回落到旧库。
    """

    method: MemoryMethod
    resources: tuple[StateResource, ...]
    management: MemoryAdministration | None = None
    legacy_sqlite: bool = False


def require_management(administration: MemoryAdministration | None,
                       capability: str) -> MemoryAdministration:
    if capability not in ManagementCapabilities.__dataclass_fields__:
        raise ValueError("未知的管理能力。")
    if administration is None or not getattr(administration.capabilities, capability):
        raise UnsupportedCapabilityError(f"管理不支持能力：{capability}")
    return administration
