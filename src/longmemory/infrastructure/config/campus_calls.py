"""所有者确认校园免费后的调用审计；不是另一个付费预算池，不接触官方账本。"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from time import time
from types import SimpleNamespace
from uuid import uuid4

from longmemory.methods.hy_memory.budget import GatewayDiagnostics


class FreeCampusCalls(GatewayDiagnostics):
    billing_mode = "owner_confirmed_free"

    def __init__(self, path, *, proof, create=False):
        self.path = Path(path)
        self.proof = proof
        self.policy = SimpleNamespace(model=proof["request_model"])
        body = json.dumps(proof, sort_keys=True)
        self.identity = hashlib.sha256(body.encode()).hexdigest()
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("xb"):
                pass
            with self._connect() as connection:
                connection.executescript("CREATE TABLE policy(body TEXT NOT NULL); CREATE TABLE calls(id TEXT PRIMARY KEY, phase TEXT NOT NULL, state TEXT NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, created REAL NOT NULL);")
                connection.execute("INSERT INTO policy VALUES (?)", (body,))
        elif not self.path.is_file():
            raise FileNotFoundError("campus_calls_existing_ledger_required")
        with self._connect() as connection:
            if connection.execute("SELECT body FROM policy").fetchone()[0] != body:
                raise ValueError("campus_calls_identity_changed")
            # 前任reserved保持不确定，不在领取引擎独占锁前改写，更不自动重发。

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path.resolve().as_uri()+"?mode=rw", uri=True, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def reserve(self, phase):
        if phase not in {"hy", "baseline", "answer", "probe"}:
            raise ValueError("campus_call_phase_invalid")
        aid = uuid4().hex
        with self._connect() as connection:
            connection.execute("INSERT INTO calls VALUES (?,?,'reserved',NULL,NULL,NULL,?)", (aid, phase, time()))
        return aid

    def finish(self, aid, usage=None, *, successful=False):
        valid = successful and isinstance(usage, dict)
        values = [usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")] if valid else [None]*3
        valid = valid and all(type(value) is int and value >= 0 for value in values) and sum(values[:2]) == values[2]
        with self._connect() as connection:
            result = connection.execute("UPDATE calls SET state=?,prompt_tokens=?,completion_tokens=?,total_tokens=? WHERE id=? AND state='reserved'",
                ("completed" if valid else "unknown", *(values if valid else [None]*3), aid))
            if result.rowcount != 1:
                raise ValueError("campus_call_not_reserved")

    def status(self):
        try:
            with self._connect() as connection:
                count, unknown, prompt, completion = connection.execute("SELECT COUNT(*),COALESCE(SUM(state<>'completed'),0),COALESCE(SUM(prompt_tokens),0),COALESCE(SUM(completion_tokens),0) FROM calls").fetchone()
            return {"state": "available", "reason": None, "billing_policy": self.billing_mode,
                "personal_cost_micro_cny": 0, "held_or_settled_upper_micro_cny": 0,
                "limit_micro_cny": None, "currency": None, "account_currency_verified": False,
                "cost_authority": "owner_confirmation",
                "attempt_count": count, "unknown_or_inflight": unknown,
                "observed_prompt_tokens": prompt, "observed_completion_tokens": completion,
                "price_policy_sha256": self.identity, "official_budget_reused_or_released": False}
        except (OSError, sqlite3.Error):
            return {"state": "paused", "reason": "campus_call_ledger_unavailable", "billing_policy": self.billing_mode}


def open_campus_calls(root, model, *, create=False):
    from .hy_deployment import _path
    root = Path(root).resolve()
    path = root / "local/config/hy-memory/provider-policy.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError("campus_free_policy_required")
    proof = json.loads(path.read_text(encoding="utf-8"))
    required = {"version", "profile", "billing_mode", "personal_cost_micro_cny", "source",
                "confirmed_date", "endpoint_sha256", "request_model", "credential_sha256", "ledger_path"}
    if (not isinstance(proof, dict) or set(proof) != required or proof["version"] != 1
            or proof["profile"] != "campus" or proof["billing_mode"] != "owner_confirmed_free"
            or type(proof["personal_cost_micro_cny"]) is not int or proof["personal_cost_micro_cny"] != 0
            or proof["source"] != "owner_confirmation" or proof["confirmed_date"] != "2026-10-19"
            or proof["endpoint_sha256"] != hashlib.sha256(model.base_url.encode()).hexdigest()
            or proof["credential_sha256"] != hashlib.sha256(model.api_key.encode()).hexdigest()
            or proof["request_model"] != model.model):
        raise ValueError("campus_free_policy_identity_mismatch")
    ledger = _path(root, proof["ledger_path"], parent="data/databases")
    return FreeCampusCalls(ledger, proof=proof, create=create)
