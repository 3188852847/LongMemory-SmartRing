"""续用同一十元池；只续核价期限，不重建额度、尝试或失败预留。"""

from dataclasses import asdict, replace
import hashlib
import json
import sqlite3
from threading import RLock
from time import time

from longmemory.methods.hy_memory.budget import SharedBudget, PricePolicy, BudgetStopped


PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
CAMPAIGN_RELATIVE = "local/worktrees/v-hy-memory-20261019/local/runtime/hy-memory/real-validation-20261019/budget.db"


class ExistingCampaignBudget(SharedBudget):
    def __init__(self, path):
        if not path.is_file():
            raise FileNotFoundError("existing_campaign_budget_required")
        self._policy_lock = RLock()
        super().__init__(path, create=False)
        self._baseline = asdict(self.policy)
        self._baseline.pop("expires_at_unix")

    def _refresh(self):
        with self._connect() as connection:
            policy = PricePolicy(**json.loads(connection.execute("SELECT body FROM policy").fetchone()[0]))
        identity = asdict(policy)
        identity.pop("expires_at_unix")
        if identity != self._baseline:
            raise BudgetStopped("budget_policy_changed")
        self.policy = policy

    def reserve(self, phase):
        with self._policy_lock:
            self._refresh()
            return super().reserve(phase)

    def renew_verified_price(self, proof):
        """由受控启动消费所有者保存的官方核价回执；不自行联网或自动延时。"""
        required = {"source", "verified_at_unix", "valid_until_unix", "model", "currency",
                    "input_micro_cny_per_token", "output_micro_cny_per_token", "currency_verified"}
        if not isinstance(proof, dict) or set(proof) != required:
            raise ValueError("price_verification_invalid")
        start, end = proof["verified_at_unix"], proof["valid_until_unix"]
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not start <= time() < end <= start + 7200
                or proof["source"] != PRICE_SOURCE or proof["currency"] != "CNY"
                or proof["currency_verified"] is not True):
            raise ValueError("price_verification_expired_or_untrusted")
        with self._policy_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = PricePolicy(**json.loads(connection.execute("SELECT body FROM policy").fetchone()[0]))
            if any(proof[key] != getattr(old, key) for key in ("model", "input_micro_cny_per_token", "output_micro_cny_per_token")):
                raise ValueError("price_verification_changes_campaign")
            if end <= old.expires_at_unix:
                return
            new = replace(old, expires_at_unix=end)
            old_body, new_body = (json.dumps(asdict(item), sort_keys=True) for item in (old, new))
            connection.execute("CREATE TABLE IF NOT EXISTS price_renewals (old_sha256 TEXT, new_sha256 TEXT, verified_at REAL, expires_at REAL, source TEXT)")
            connection.execute("INSERT INTO price_renewals VALUES (?,?,?,?,?)", (
                hashlib.sha256(old_body.encode()).hexdigest(), hashlib.sha256(new_body.encode()).hexdigest(), start, end, PRICE_SOURCE))
            connection.execute("UPDATE policy SET body=?", (new_body,))
            self.policy = new

    def status(self):
        with self._policy_lock:
            try:
                self._refresh()
                result = self.report()
                reason = None
                bound = self.policy.input_window_bound + self.policy.output_window_bound
                if self.policy.expires_at_unix <= time():
                    reason = "budget_price_expired"
                elif (result["attempt_count"] >= self.policy.max_requests
                        or result["held_or_settled_upper_micro_cny"] + self.policy.reservation > self.policy.limit_micro_cny
                        or sum(row["token_bound"] for row in result["attempts"]) + bound > self.policy.max_total_tokens_bound):
                    reason = "budget_global_limit_reached"
                return {key: value for key, value in result.items() if key != "attempts"} | {
                    "state": "paused" if reason else "available", "reason": reason,
                    "price_expires_at_unix": self.policy.expires_at_unix}
            except (ValueError, BudgetStopped, OSError, sqlite3.Error):
                return {"state": "paused", "reason": "budget_policy_changed"}
