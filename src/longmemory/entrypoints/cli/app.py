"""V0.1 文本 CLI 的启动与主循环。"""

from argparse import ArgumentParser
from collections.abc import Callable, Sequence
from pathlib import Path
import os

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.infrastructure.config.settings import load_model_settings, database_path_from_env
from longmemory.infrastructure.logging.setup import configure_file_logging, close_file_logging

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

def run_chat_session(
    application: LongMemoryApplication,
    *,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
    provider_label: str = "Fake（离线规则替身）",
) -> None:
    """运行一个可注入输入输出函数的交互会话。

    注入 input_fn 和 output_fn 后，可以在自动化测试中模拟终端，
    无需真的等待人工键盘输入。
    """

    output_fn(f"LongMemory V0.1\n回答器：{provider_label}\n提取仍为规则，检索仍为关键词。输入 /help 查看命令。")

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

        try:
            chat_result = application.chat(user_input)
        except AnswerGenerationError as error:
            output_fn(f"回答失败：{error}\n本轮用户输入及已提取的记忆可能已保存；未保存成功的助手回答。")
            continue
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
        default=None,
        help=(
            "SQLite 数据库路径，默认是 "
            "data/databases/longmemory.db"
        ),
    )

    parser.add_argument("--provider", choices=("fake", "openai_compatible"))
    parser.add_argument("--check-model", action="store_true", help="只发送一句合成连通性请求，不打开数据库")
    parser.add_argument("--log-file", type=Path, default=None, help="JSONL 审计日志路径，仅记录元数据")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """启动 LongMemory CLI，并在退出时关闭数据库。"""

    parser = build_parser()
    arguments = parser.parse_args(
        list(argv) if argv is not None else None
    )

    try:
        settings = load_model_settings(provider=arguments.provider)
    except ValueError as error:
        print(f"配置错误：{error}")
        return 2
    generator = (FakeAnswerGenerator() if settings.provider == "fake"
                 else OpenAICompatibleAnswerGenerator(settings))
    if settings.provider == "openai_compatible" and settings.allow_http:
        print("警告：HTTP 会明文传输凭据与内容。仅在确认风险的校园网合成测试中使用。")
    if arguments.check_model:
        if settings.provider == "fake":
            print("--check-model 需要选择 openai_compatible，不能用 Fake 冒充真实验证。")
            return 2
        try:
            generator.generate(query="这是合成连通性测试，请仅回复 OK。", memory_context="")
        except AnswerGenerationError as error:
            print(f"连接验证失败：{error}")
            return 1
        print("连接验证通过：收到非空兼容响应。此结果不代表记忆问答质量通过。")
        return 0

    database_path = arguments.database or database_path_from_env()
    log_path = arguments.log_file or Path(os.environ.get("LONGMEMORY_LOG_PATH", "data/logs/events.jsonl"))
    handler = configure_file_logging(log_path)
    try:
        application = build_application(database_path=database_path, answer_generator=generator)
        print(f"数据库：{database_path.resolve()}")
        try:
            label = "Fake（离线规则替身）" if settings.provider == "fake" else settings.model
            run_chat_session(application, provider_label=label)
        finally:
            application.close()
    finally:
        close_file_logging(handler)

    return 0
