#!/usr/bin/env python3
"""s01: Agent Loop —— 一个循环 + 一个 bash 工具 = 一个 Agent。

本文件只做"组装"：把 core.loop（循环引擎）和 tools.bash（工具）拼到一起。
核心逻辑在 core/loop.py；学习笔记在 docs/s01-notes.md。

运行方式：python agents/s01_agent_loop.py
"""
from __future__ import annotations  # 启用延迟类型注解求值

import os  # 操作系统接口，用于获取当前工作目录
import sys  # 系统模块，用于修改 Python 模块搜索路径
from pathlib import Path  # 路径工具，用于构建绝对路径

# 把项目根目录插入到 sys.path 的最前面，
# 这样才能用 from core.xxx import yyy 这种导入方式
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 从 core 层导入 agent_loop 函数（驱动循环的核心引擎）
from core.loop import agent_loop
# 从 tools 层导入 bash 模块（提供 SCHEMA 和 run 函数）
from tools import bash

# 系统提示词：告诉模型它的角色、工作目录和行为风格
# f-string 中的 {os.getcwd()} 会被替换为当前工作目录的绝对路径
SYSTEM = (
    f"You are a coding agent working at {os.getcwd()}. "
    "Use the `bash` tool to accomplish the user's task. Act, don't over-explain."
)

# 工具列表：传给 API 的工具 schema 数组，s02 起这里会变长
TOOLS = [bash.SCHEMA]

# 工具处理函数映射：工具名 → 执行函数，s02 起这里会新增条目
HANDLERS = {"bash": bash.run}


def _print_tool_call(name: str, args: dict, output: str) -> None:
    """打印工具调用的可视化信息（黄色高亮）。

    参数：
        name: 工具名称（如 "bash"）
        args: 模型传给工具的参数字典
        output: 工具执行后返回的输出字符串
    """
    # 如果是 bash 工具，用 $ 符号展示命令（模拟终端风格）
    if name == "bash":
        # \033[33m 是 ANSI 黄色转义码，\033[0m 是重置颜色
        print(f"\033[33m$ {args.get('command', '')}\033[0m")
    else:
        # 其他工具用 [工具名] 的格式展示参数
        print(f"\033[33m[{name}] {args}\033[0m")

    # 打印工具输出，超长输出截断到 400 字符，避免刷屏
    preview = output if len(output) < 400 else output[:400] + " ...(truncated)"
    print(preview)


def _print_assistant_text(messages: list) -> None:
    """打印模型最后的文本回复（绿色高亮）。

    参数：
        messages: 完整的对话历史列表
    """
    # 取对话历史的最后一条消息
    last = messages[-1]

    # 确保最后一条是 assistant 消息（否则不打印）
    if last["role"] != "assistant":
        return

    # 遍历最后一条 assistant 消息中的所有内容块
    for block in last["content"]:
        # 尝试获取 text 属性（文本块有 text，工具调用块没有）
        text = getattr(block, "text", None)

        # 如果有文本内容且不是纯空白，就用绿色打印出来
        if text and text.strip():
            # \033[32m 是 ANSI 绿色转义码
            print(f"\033[32m{text.strip()}\033[0m")


def main() -> None:
    """REPL 主循环：读取用户输入 → 调用 agent_loop → 打印结果。"""
    # 打印欢迎信息（青色）
    # \033[36m 是 ANSI 青色转义码
    print("\033[36m== s01: Agent Loop ==\033[0m  (q / exit 退出)")

    # 初始化对话历史列表，整个 REPL 会话共享同一个 history
    history: list = []

    # REPL 外循环：每次用户输入一个 prompt 就走一轮 agent_loop
    while True:
        try:
            # 等待用户输入，提示符为青色的 "s01 >> "
            query = input("\033[36ms01 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D (EOF) 或 Ctrl+C：打印换行后优雅退出
            print()
            return

        # 如果用户输入 q、exit 或空行，退出 REPL
        if query.lower() in {"q", "exit", ""}:
            return

        # 把用户的输入追加到对话历史（user 角色）
        history.append({"role": "user", "content": query})

        # 调用核心 agent_loop 函数，驱动模型思考 + 工具执行的循环
        # history 会被就地修改（追加 assistant 和 user 消息）
        stop_reason = agent_loop(
            history,  # 对话历史（就地修改）
            system=SYSTEM,  # 系统提示词
            tools=TOOLS,  # 工具 schema 列表
            handlers=HANDLERS,  # 工具处理函数映射
            on_tool_call=_print_tool_call,  # 工具调用时的打印回调
        )

        # agent_loop 结束后，打印模型的最终文本回复
        _print_assistant_text(history)

        # 打印本轮循环的元信息（灰色）：退出原因和总轮次数
        # \033[90m 是 ANSI 暗灰色转义码
        print(f"\033[90m[loop exit] stop_reason={stop_reason}  turns={_count_turns(history)}\033[0m\n")


def _count_turns(messages: list) -> int:
    """统计对话历史中有多少轮 assistant 消息（即模型被调用了几次）。

    参数：
        messages: 完整的对话历史列表

    返回：
        assistant 消息的数量（整数）
    """
    # 遍历所有消息，统计 role == "assistant" 的条数
    return sum(1 for m in messages if m["role"] == "assistant")


# 当脚本被直接运行时（而非被 import），执行 main 函数
if __name__ == "__main__":
    main()
