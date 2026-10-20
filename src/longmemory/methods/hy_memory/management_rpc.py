"""固定 SDK 的单条管理边界；平台权限、修订、来源和审计仍由 Y/X 负责。"""

import json
import errno
import os

from .sdk_bridge import SDK_VERSION, SOURCE_NAMESPACE, HyResponseError, _sources


def profile_scope_proof(workspace, settings, *, create, fresh, verified):
    """可信装配仅在空的新库建立范围证明；既有库不能靠开关补发证明。"""
    if not settings.management_exclusive_profile or not verified:
        return False
    path = workspace / "management-scope.json"
    expected = {"protocol":1, "sdk_version":SDK_VERSION, "identity":settings.identity(),
        "user_id":settings.user_id, "agent_id":settings.agent_id, "source":SOURCE_NAMESPACE,
        "origin":"empty_sdk_created_by_scoped_worker"}
    if create and fresh:
        with path.open("x",encoding="utf-8") as stream:
            json.dump(expected,stream,ensure_ascii=False,sort_keys=True)
    if path.is_symlink() or path.is_junction():
        return False
    try:
        return json.loads(path.read_text(encoding="utf-8")) == expected
    except (OSError, ValueError):
        return False


class HyManagementDenied(ValueError):
    """未进入 SDK 写操作；不携带外部正文或身份。"""


def validate_owned_row(row, settings, memory_id, *, writable=False):
    """平台写前和worker复查使用相同的确定性范围规则。"""
    if (not isinstance(row, dict) or row.get("memory_id") != memory_id
            or row.get("user_id") != settings.user_id or row.get("agent_id") != settings.agent_id
            or row.get("source") != "vdb"):
        raise HyManagementDenied("hy_management_item_scope_unproven")
    meta = row.get("meta")
    if (not isinstance(meta, list) or not meta or any(not isinstance(entry, dict)
            or entry.get("namespace") != SOURCE_NAMESPACE or entry.get("role") != "user" for entry in meta)):
        raise HyManagementDenied("hy_management_source_scope_unproven")
    try:
        sources = _sources(meta)
    except HyResponseError:
        sources = None
    if not sources:
        raise HyManagementDenied("hy_management_source_scope_unproven")
    if writable and (row.get("layer") not in {"l2_fact", "l3_summary"}
            or row.get("status") != "active" or row.get("is_latest") is not True):
        raise HyManagementDenied("hy_management_item_read_only")
    return row


def validate_write_input(operation, arguments):
    memory_id = ManagementRPC._identifier(arguments["memory_id"])
    if operation == "update":
        content = arguments["content"]
        if not isinstance(content, str) or not content.strip() or len(content) > 1000 or "\0" in content:
            raise HyManagementDenied("hy_management_content_invalid")
    return memory_id


def validate_management_write(row, settings, operation, arguments):
    memory_id = validate_write_input(operation, arguments)
    validate_owned_row(row, settings, memory_id, writable=True)
    if operation == "delete" and (row.get("supersedes") != [] or row.get("superseded_by") != []):
        raise HyManagementDenied("hy_management_delete_evolution_refused")


def owner_lease_held(workspace):
    """只探测已存在的 owner 锁；不创建/接管租约，唯一拥有者仍归 X/Y。"""
    try:
        owner = workspace/"engine.owner"
        if owner.is_symlink() or owner.is_junction():
            return False
        with owner.open("r+b") as stream:
            # Windows 的字节锁同时阻止读取被锁字节；用文件长度检查，不先 read。
            if os.fstat(stream.fileno()).st_size < 1:
                return False
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    fcntl.flock(stream,fcntl.LOCK_UN)
            except OSError as exc:
                return exc.errno in {errno.EACCES,errno.EAGAIN,errno.EDEADLK}
    except OSError:
        return False
    return False


class ManagementRPC:
    OPERATIONS = {"management_capabilities", "history", "update", "delete"}

    def __init__(self, client, settings, budget):
        self.client, self.settings, self.budget = client, settings, budget

    def capabilities(self):
        verified = getattr(self.budget, "actual_sdk_version", None) == SDK_VERSION
        semantic = getattr(self.budget, "semantic", None)
        safe_update = bool(getattr(self.budget, "management_update_verified", False) or
            (semantic is not None and self.settings.semantic_layers_enabled and not semantic._work.locked()))
        transport = self.settings.model_mode == "synthetic_transport" or (
            self.settings.network_authorized and self.settings.managed_gateway)
        update = (verified and safe_update and self.settings.management_writes_enabled
            and transport and callable(getattr(self.client, "update", None))
            and callable(getattr(self.client, "get", None)))
        deletion = (verified and safe_update and self.settings.management_writes_enabled
            and callable(getattr(self.client,"delete",None)) and callable(getattr(self.client,"get",None)))
        profile = (verified and self.settings.management_exclusive_profile
            and getattr(self.budget,"management_profile_scope_proven",False) is True
            and getattr(self.budget,"management_workspace",None) is not None
            and owner_lease_held(self.budget.management_workspace)
            and callable(getattr(self.client,"get_user_profile",None)))
        return {"protocol": 1,
            "history": bool(verified and callable(getattr(self.client, "history", None))
                and callable(getattr(self.client, "get", None))),
            "profile": bool(profile), "exclusive_user_profile": bool(profile),
            "update": bool(update), "delete": bool(deletion),
            "history_recording": False,
            "limitations": {
                "profile": ("trusted_empty_space_scope_stamp_and_fixed_worker_identity;requires_external_owner_lease"
                    if profile else "requires_trusted_empty_space_stamp_user_agent_source_and_external_owner_lease"),
                "delete": ("isolated_active_l2_l3_only_any_evolution_link_refused"
                    if deletion else "requires_verified_chroma_graph_clause_off_and_explicit_write"),
                "history": "sdk_history_recording_disabled_empty_is_not_no_changes",
                "update": ("single_active_l2_l3_content_embedding_only_raw_meta_history_preserved"
                    if update else "requires_verified_chroma_graph_clause_off_explicit_write_and_local_embedding_transport"),
                "native_atomic_revision": False,
                **({"semantic_derivatives": "archive_scoped_graph_and_same_source_intentions_before_mutation;busy_while_evolve;no_native_cas"}
                    if semantic is not None else {}),
            }}

    @staticmethod
    def _identifier(value):
        if (not isinstance(value, str) or not value.strip() or len(value) > 256
                or value in {".", ".."} or any(ord(char) < 32 or char in "/\\" for char in value)):
            raise HyManagementDenied("hy_management_id_invalid")
        return value

    def _owned(self, memory_id, *, writable=False):
        return validate_owned_row(self.client.get(memory_id), self.settings, memory_id, writable=writable)

    def execute(self, operation, arguments):
        expected = ({"memory_id", "content"} if operation == "update"
            else set() if operation == "management_capabilities" else {"memory_id"})
        if operation not in self.OPERATIONS or not isinstance(arguments, dict) or set(arguments) != expected:
            raise HyManagementDenied("hy_management_arguments_invalid")
        caps = self.capabilities()
        if operation == "management_capabilities":
            return caps
        memory_id = self._identifier(arguments["memory_id"])
        if not caps[operation]:
            raise HyManagementDenied("hy_management_operation_unavailable")
        if operation in {"update", "delete"}:
            validate_write_input(operation, arguments)
            validate_management_write(self.client.get(memory_id), self.settings, operation, arguments)
        else:
            self._owned(memory_id)
        # 不调用 add/重新提取，不把平台来源伪装进 SDK meta；不做任何自动重试。
        semantic = getattr(self.budget, "semantic", None)
        guarded = semantic is not None and operation in {"update", "delete"}
        if guarded:
            semantic.begin_management(self.client.get(memory_id))
        elif operation in {"update","delete"}:
            from .semantic import invalidate_inactive_semantics
            invalidate_inactive_semantics(getattr(self.budget,"management_workspace",None))
        try:
            result = getattr(self.client, operation)(**arguments)
        finally:
            if guarded:
                semantic.end_management()
        if operation == "history":
            if not isinstance(result, list) or any(not isinstance(row, dict)
                    or row.get("memory_id") != memory_id for row in result):
                raise HyResponseError("hy_management_history_invalid")
        elif operation == "delete":
            if (not isinstance(result,dict) or result.get("success") is not True
                    or type(result.get("deleted_count")) is not int or result["deleted_count"] != 1):
                raise HyResponseError("hy_management_write_result_invalid_state_unknown")
        elif (not isinstance(result, dict) or result.get("success") is not True
                or result.get("memory_id") != memory_id):
            raise HyResponseError("hy_management_write_result_invalid_state_unknown")
        return result
