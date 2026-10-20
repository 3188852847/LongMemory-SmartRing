"""固定真实SDK、人工类型fixture；只在新合成空间播种，不代表模型提取质量。"""

from datetime import UTC, datetime, timedelta

from longmemory.methods.hy_memory.worker import ProtocolService, create_sdk, main
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE


def run(scenario="normal"):
    def factory(settings, workspace, *, create):
        client, budget = create_sdk(settings, workspace, create=create)
        if create and scenario != "unseeded":
            from hy_memory.models.memory import MemoryNode, MemoryLayer, MemoryStatus
            async def seed():
                store = client._vector_store
                moment = datetime(2026, 1, 1, tzinfo=UTC)
                def node(name, layer, content, *, status="active", custom=None, user=None, agent=None, source=SOURCE_NAMESPACE, seconds=0, **kwargs):
                    return MemoryNode(node_id=name, user_id=user or settings.user_id,
                        agent_id=settings.agent_id if agent is None else agent, source=source,
                        layer=MemoryLayer(layer), content=content, status=MemoryStatus(status),
                        gmt_created=moment + timedelta(seconds=seconds),
                        embedding=[1.0] + [0.0] * (settings.embedding_dimensions - 1),
                        custom=custom or {"meta": [{"namespace": SOURCE_NAMESPACE, "role": "user", "source_event_ids": ["source:" + name]}]}, **kwargs)
                rows = [node("raw-native", "l1_raw", "真正SDK RAW fixture，不是平台归档"),
                    node("summary-native", "l3_summary", "人工插入的SDK摘要类型"),
                    node("identity-native", "l4_identity", "人工插入的历史兼容身份记录"),
                    node("knowledge-native", "l5_knowledge", "保留类型人工fixture，非已实现的知识生成"),
                    node("schema-native", "l6_schema", "图式类型VDB fixture，非System2产出"),
                    node("intention-native", "l7_intention", "意图类型VDB fixture，未开启意图提取"),
                    node("long-native", "l2_fact", "长" * 40000),
                    node("other-user", "l2_fact", "PRIVATE_OTHER_USER", user="other-user"),
                    node("other-agent", "l2_fact", "PRIVATE_OTHER_AGENT", agent="other-agent"),
                    node("other-source", "l2_fact", "PRIVATE_OTHER_SOURCE", source="other-source"),
                    node("other-layer", "l1_raw", "同范围不同层")]
                for index, state in enumerate(("active", "active", "superseded", "negated", "conflicted", "shadow", "archived")):
                    rows.append(node("fact-" + str(index), "l2_fact", "事实状态 " + state, status=state,
                        is_latest=state == "active", seconds=index, supersedes=["fact-2"] if index == 0 else None))
                def profile(name, kv, seconds, status="active", **kwargs):
                    return node(name, "l0_basic_info", "当前节点只存diff，不可冒充聚合", agent="", source="default",
                        status=status, seconds=seconds,
                        custom={"basic_info_kv": kv, "meta": [{"namespace": SOURCE_NAMESPACE,
                            "role": "user", "source_event_ids": ["source:" + name]}]}, **kwargs)
                rows.extend((profile("profile-old", {"name": "合成小明", "location": "甲城"}, 1, "superseded", is_latest=False, superseded_by=["profile-new"]),
                             profile("profile-new", {"location": "乙城"}, 2, supersedes=["profile-old"])))
                if scenario == "profile_limit":
                    for index in range(129):
                        rows.append(profile("profile-limit-" + str(index), {"name": "合成用户"}, index + 3))
                if scenario == "scope_bad":
                    rows.append(node("profile-foreign", "l0_basic_info", "PRIVATE_FOREIGN_PROFILE", agent="other-agent", source="other-source",
                        custom={"basic_info_kv": {"name": "PRIVATE_FOREIGN_PROFILE"},
                            "meta": [{"namespace": "other-source", "source_event_ids": ["private"]}]}))
                if scenario == "profile_variants":
                    rows.extend((profile("profile-negated", {"occupation": "合成职业"}, 3, "negated", is_latest=False),
                        profile("profile-branch", {"location": "丙城"}, 4),
                        profile("profile-null", {"name": None, "employer": ""}, 5, "archived", is_latest=False)))
                await store.upsert_batch(rows)
            client._loop_thread.run(seed())
            if scenario == "graph_marker":
                # 模拟旧图资源存在，不能当可读真实Kuzu数据或空图证据。
                (workspace / "sdk" / "graph").write_bytes(b"synthetic-existing-graph-marker")
        return client, budget
    main(service=ProtocolService(factory=factory))
