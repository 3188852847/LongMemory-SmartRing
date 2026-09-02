"""验证 CLI、应用服务和 SQLite 的完整交互。"""

from longmemory.bootstrap import build_application
from longmemory.entrypoints.cli.app import run_chat_session


def test_cli_can_chat_list_and_delete_memory(tmp_path) -> None:
    """模拟终端输入，验证聊天、查看和删除命令。"""

    database_path = tmp_path / "longmemory.db"
    application = build_application(
        database_path=database_path
    )

    outputs: list[str] = []
    prompts: list[str] = []

    scripted_inputs: list[str | None] = [
        "我养了一只叫豆包的猫。",
        "我的猫叫什么？",
        "/memories",
        None,
        "/memories",
        "/exit",
    ]

    def fake_input(prompt: str) -> str:
        """按照脚本返回输入，删除步骤动态读取真实记忆 ID。"""

        prompts.append(prompt)
        input_index = len(prompts) - 1
        scripted_input = scripted_inputs[input_index]

        if scripted_input is None:
            memories = application.list_memories()
            memory_id = memories[0].memory.id
            return f"/delete {memory_id}"

        return scripted_input

    try:
        run_chat_session(
            application,
            input_fn=fake_input,
            output_fn=outputs.append,
        )

        combined_output = "\n".join(outputs)

        assert "助手：好的，我记住了。" in combined_output
        assert "本轮保存了 1 条长期记忆。" in combined_output
        assert "助手：你的猫叫豆包。" in combined_output

        assert "内容：用户养了一只叫豆包的猫。" in (
            combined_output
        )
        assert "来源：我养了一只叫豆包的猫。" in (
            combined_output
        )

        assert "已删除记忆：" in combined_output
        assert "当前没有保存的长期记忆。" in combined_output
        assert "已退出 LongMemory。" in combined_output

        assert application.list_memories() == ()
    finally:
        application.close()

    # 重新打开数据库，确认 CLI 删除操作已经持久化。
    reopened_application = build_application(
        database_path=database_path
    )

    try:
        assert reopened_application.list_memories() == ()
    finally:
        reopened_application.close()