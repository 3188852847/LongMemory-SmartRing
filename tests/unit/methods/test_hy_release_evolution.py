"""A returned evolution head must preserve management rules of visible versions."""

from types import SimpleNamespace

from longmemory.methods.hy_memory.administration import HyAdministration
from longmemory.methods.hy_memory.method import HyMemoryMethod
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE
from longmemory.methods.hy_memory.settings import HySettings


class EvolutionClient:
    def __init__(self, root):
        self.state = SimpleNamespace(root=root, _lease=object())

    def search(self, *args, **kwargs):
        # Real SDK search returns the chain head with visible history embedded in
        # content; the management operation belongs to the older version's ID.
        row = {"memory_id": "head", "layer": "l2_fact",
            "content": "- Current: 合成新事实\n  History:\n  - 合成管理纠正后的旧事实",
            "meta": [{"namespace": SOURCE_NAMESPACE, "source_event_ids": ["original", "latest"]}],
            "evolution_chain": [{"node_id": "head", "content": "合成新事实"},
                                {"node_id": "older", "content": "合成管理纠正后的旧事实"}]}
        return {"request_id": "z-chain", "memories": {"normal": [row], "schema": [], "proactive": []}}

    def close(self):
        pass


def configured(root, state):
    client = EvolutionClient(root)
    method = HyMemoryMethod(settings=HySettings(user_id="z-chain-user"), client_factory=lambda: client)
    admin = HyAdministration(method)
    with admin._ledger() as db:
        db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,NULL)",
            ("z-chain-request", "synthetic-hash", "correct", "older", "z-correction-source", "a" * 64,
             state, "2026-10-19T00:00:00+00:00"))
    return method


def test_visible_evolution_version_carries_completed_correction_source(tmp_path):
    method = configured(tmp_path, "completed")
    try:
        support = method.recall("合成历史问题")
        assert "z-correction-source" in support.retrieved[0].source_event_ids
    finally:
        method.close()


def test_visible_evolution_version_uncertain_blocks_history_injection(tmp_path):
    method = configured(tmp_path, "uncertain")
    try:
        support = method.recall("合成历史问题")
        assert support.retrieved == ()
        assert support.context == ""
        assert support.warning_code == "hy_management_uncertain_items_excluded"
    finally:
        method.close()
