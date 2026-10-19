from dataclasses import asdict
import json
import sqlite3
from time import time

import pytest

from longmemory.infrastructure.config.hy_campaign import ExistingCampaignBudget, PRICE_SOURCE
from longmemory.methods.hy_memory.budget import SharedBudget, PricePolicy, BudgetStopped


def seed(path, *, unknown=False):
    budget = SharedBudget(path, policy=PricePolicy(expires_at_unix=time()+60), create=True)
    attempt = budget.reserve("probe")
    budget.finish(attempt, {"prompt_tokens":245511, "completion_tokens":0, "total_tokens":245511}, successful=True)
    if unknown:
        budget.finish(budget.reserve("answer"), None, successful=False)
    return budget


def proof():
    return {"source": PRICE_SOURCE, "verified_at_unix": time()-1, "valid_until_unix": time()+3600,
        "currency": "CNY", "currency_verified": True, "model": "deepseek-v4-flash",
        "input_micro_cny_per_token": 2, "output_micro_cny_per_token": 8}


def test_existing_pool_renewal_preserves_spend_and_failed_reservation_across_restart(tmp_path):
    path = tmp_path / "budget.db"
    original = seed(path, unknown=True)
    before = original.report()
    budget = ExistingCampaignBudget(path)
    budget.renew_verified_price(proof())
    reopened = ExistingCampaignBudget(path)
    after = reopened.report()
    assert after["attempts"] == before["attempts"]
    assert after["held_or_settled_upper_micro_cny"] == 491022 + original.policy.reservation
    assert reopened.status()["reason"] == "budget_global_limit_reached"
    with pytest.raises(BudgetStopped): reopened.reserve("answer")
    assert reopened.report()["attempt_count"] == before["attempt_count"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM price_renewals").fetchone()[0] == 1


@pytest.mark.parametrize("change", [{"valid_until_unix":0}, {"input_micro_cny_per_token":1},
    {"model":"deepseek-flash"}, {"source":"https://untrusted.invalid"}, {"limit_micro_cny":20000000}])
def test_untrusted_or_changed_price_cannot_renew_or_reset_existing_pool(tmp_path, change):
    path = tmp_path / "budget.db"
    seed(path)
    budget = ExistingCampaignBudget(path)
    before = budget.report()
    with pytest.raises(ValueError): budget.renew_verified_price(proof() | change)
    assert budget.report() == before


def test_missing_pool_not_created_and_expired_price_stops_before_paid_attempt(tmp_path):
    path = tmp_path / "budget.db"
    with pytest.raises(FileNotFoundError): ExistingCampaignBudget(path)
    assert not path.exists()
    original = seed(path)
    with sqlite3.connect(path) as connection:
        policy = asdict(original.policy) | {"expires_at_unix":0}
        connection.execute("UPDATE policy SET body=?", (json.dumps(policy),))
    budget = ExistingCampaignBudget(path)
    assert budget.status()["reason"] == "budget_price_expired"
    with pytest.raises(BudgetStopped): budget.reserve("hy")
    assert budget.report()["attempt_count"] == 1
