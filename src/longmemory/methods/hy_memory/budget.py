"""跨进程、跨方法的持久费用预留；不存请求正文或凭据。"""

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from time import time
from uuid import uuid4


class BudgetStopped(RuntimeError):
    pass


@dataclass(frozen=True)
class PricePolicy:
    model: str = "deepseek-v4-flash"
    currency: str = "CNY"
    input_micro_cny_per_token: int = 2
    output_micro_cny_per_token: int = 8
    # 官方 1M/384K 的上界再放大到 2Mi/512Ki，避免 M/K 单位解释和模板差异。
    input_window_bound: int = 2_097_152
    output_window_bound: int = 524_288
    limit_micro_cny: int = 10_000_000
    max_requests: int = 400
    max_total_tokens_bound: int = 10_000_000
    expires_at_unix: float = 0
    source: str = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"

    def __post_init__(self):
        if self.currency != "CNY" or self.model not in {"deepseek-v4-flash", "deepseek-flash"}:
            raise ValueError("budget_unverified_price_model")
        for key, value in asdict(self).items():
            if key not in {"model","currency","source","expires_at_unix"} and (type(value) is not int or value <= 0):
                raise ValueError("budget_policy_invalid")
        if self.limit_micro_cny > 10_000_000:
            raise ValueError("budget_exceeds_user_cny10")

    @property
    def reservation(self):
        return (self.input_window_bound*self.input_micro_cny_per_token
                + self.output_window_bound*self.output_micro_cny_per_token)


class SharedBudget:
    def __init__(self, path: Path, *, policy=None, create=False):
        self.path = path.resolve()
        if create:
            if policy is None or policy.expires_at_unix <= time():
                raise ValueError("budget_price_expired")
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open("xb"): pass
            with self._connect() as connection:
                connection.executescript("CREATE TABLE policy(body TEXT NOT NULL); CREATE TABLE attempts(id TEXT PRIMARY KEY, phase TEXT NOT NULL, state TEXT NOT NULL, held INTEGER NOT NULL, token_bound INTEGER NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER, created REAL NOT NULL);")
                connection.execute("INSERT INTO policy VALUES (?)",(json.dumps(asdict(policy),sort_keys=True),))
        with self._connect() as connection:
            row = connection.execute("SELECT body FROM policy").fetchone()
            self.policy = PricePolicy(**json.loads(row[0]))
        if policy is not None and self.policy != policy:
            raise ValueError("budget_policy_identity_mismatch")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path.as_uri()+"?mode=rw",uri=True,timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection: yield connection
        finally:
            connection.close()

    def reserve(self, phase):
        if phase not in {"hy", "baseline", "answer", "probe"}:
            raise ValueError("budget_phase_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self.policy.expires_at_unix <= time():
                raise BudgetStopped("budget_price_expired")
            total = connection.execute("SELECT COUNT(*),COALESCE(SUM(held),0),COALESCE(SUM(token_bound),0) FROM attempts").fetchone()
            bound = self.policy.input_window_bound+self.policy.output_window_bound
            if (total[0] >= self.policy.max_requests or total[1]+self.policy.reservation > self.policy.limit_micro_cny
                    or total[2]+bound > self.policy.max_total_tokens_bound):
                raise BudgetStopped("budget_global_limit_reached")
            aid = uuid4().hex
            connection.execute("INSERT INTO attempts VALUES (?,?,'reserved',?,?,NULL,NULL,?)",
                (aid,phase,self.policy.reservation,bound,time()))
            return aid

    def finish(self, aid, usage=None, *, successful=False):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM attempts WHERE id=?",(aid,)).fetchone()
            if row is None or row["state"] != "reserved":
                raise BudgetStopped("budget_attempt_not_reserved")
            valid = successful and isinstance(usage,dict)
            prompt = usage.get("prompt_tokens") if valid else None
            completion = usage.get("completion_tokens") if valid else None
            total = usage.get("total_tokens") if valid else None
            valid = valid and type(prompt) is int and type(completion) is int and type(total) is int
            valid = valid and 0 <= prompt <= self.policy.input_window_bound and 0 <= completion <= self.policy.output_window_bound and total == prompt+completion
            if not valid:
                # HTTP 错误/超时/缺失用量/解析失败都保留完整最坏预留，不按0计。
                connection.execute("UPDATE attempts SET state='unknown' WHERE id=?",(aid,))
                return
            cost = prompt*self.policy.input_micro_cny_per_token + completion*self.policy.output_micro_cny_per_token
            connection.execute("UPDATE attempts SET state='settled',held=?,token_bound=?,prompt_tokens=?,completion_tokens=? WHERE id=?",
                (cost,total,prompt,completion,aid))

    def report(self):
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute("SELECT * FROM attempts ORDER BY created")]
        body = json.dumps(asdict(self.policy),sort_keys=True)
        return {"currency":"CNY","limit_micro_cny":self.policy.limit_micro_cny,
            "held_or_settled_upper_micro_cny":sum(row["held"] for row in rows),
            "observed_prompt_tokens":sum(row["prompt_tokens"] or 0 for row in rows),
            "observed_completion_tokens":sum(row["completion_tokens"] or 0 for row in rows),
            "unknown_or_inflight":sum(row["state"] != "settled" for row in rows),
            "attempt_count":len(rows),"price_policy_sha256":hashlib.sha256(body.encode()).hexdigest(),
            "cache_discount_applied":False,"actual_bill_verified":False,"attempts":rows}
