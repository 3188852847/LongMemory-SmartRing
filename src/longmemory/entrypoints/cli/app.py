"""V0.1 文本 CLI 的启动与主循环。"""

from argparse import ArgumentParser
from collections.abc import Callable, Sequence
from pathlib import Path

from longmemory.bootstrap import (
    LongMemoryApplication,
    build_application,
)
from longmemory.entrypoints.cli.commands import (
    HELP_TEXT,
    execute_command,
)
from longmemory.entrypoints.cli.presenter import format_chat_result


InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]

DEFAULT_DATABASE_PATH = Path(
    "data/databases/longmemory.db"
)

WELCOME_TEXT = """LongMemory V0.1 确定性原型
当前使用规则提取、关键词检索和 Fake 回答生成器。
输入 /help 查看命令。"""


def run_chat_session(
    application: LongMemoryApplication,
    *,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
) -> None:
    """运行一个可注入输入输出函数的交互会话。

    注入 input_fn 和 output_fn 后，可以在自动化测试中模拟终端，
    无需真的等待人工键盘输入。
    """

    output_fn(WELCOME_TEXT)

    while True:
        try:
            user_input = input_fn("你：")
        except EOFError:
            output_fn("输入已结束，LongMemory 已退出。")
            return
        except KeyboardInterrupt:
            output_fn("操作已中断，LongMemory 已退出。")
            return

        if not user_input.strip():
            output_fn("请输入聊天内容或 /help 查看命令。")
            continue

        command_result = execute_command(
            user_input,
            application,
        )

        if command_result.handled:
            if command_result.output is not None:
                output_fn(command_result.output)

            if command_result.should_exit:
                return

            continue

        chat_result = application.chat(user_input)
        output_fn(format_chat_result(chat_result))


def build_parser() -> ArgumentParser:
    """创建 CLI 参数解析器。"""

    parser = ArgumentParser(
        prog="longmemory",
        description="LongMemory V0.1 本地文本原型",
        epilog=HELP_TEXT,
    )

    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=(
            "SQLite 数据库路径，默认是 "
            "data/databases/longmemory.db"
        ),
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """启动 LongMemory CLI，并在退出时关闭数据库。"""

    parser = build_parser()
    arguments = parser.parse_args(
        list(argv) if argv is not None else None
    )

    database_path = arguments.database
    application = build_application(
        database_path=database_path
    )

    print(f"数据库：{database_path.resolve()}")

    try:
        run_chat_session(application)
    finally:
        application.close()

    return 0