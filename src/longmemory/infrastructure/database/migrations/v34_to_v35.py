"""V34 -> V35：把跟进候选绑定到一次性主动交流账本。"""


def migrate(connection) -> None:
    # 部分迁移回归会在最新结构上模拟旧 user_version；显式核对列也让
    # 意外中断后的迁移可安全重入，不把“列已创建”误当成数据损坏。
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(proactive_outreach)")
    }
    if "follow_up_candidate_id" not in columns:
        connection.execute(
            "ALTER TABLE proactive_outreach ADD COLUMN follow_up_candidate_id TEXT "
            "REFERENCES companion_follow_up_candidates(id) ON DELETE CASCADE"
        )
    if "follow_up_candidate_revision" not in columns:
        connection.execute(
            "ALTER TABLE proactive_outreach ADD COLUMN follow_up_candidate_revision INTEGER"
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_proactive_outreach_follow_up "
        "ON proactive_outreach(follow_up_candidate_id) "
        "WHERE follow_up_candidate_id IS NOT NULL"
    )
