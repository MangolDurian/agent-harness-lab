#!/usr/bin/env python3
"""s02: Multi-Tool —— 加一个工具只加一个 handler。

本文件只做"组装"：把 core.loop（循环引擎）和三个工具拼到一起。
相比 s01 的唯一区别：TOOLS 列表多两项，HANDLERS 多两个条目。
core/loop.py 一行不改。

运行方式：python agents/s02_multi_tool.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.loop import agent_loop
from tools import bash
from tools import read_file
from tools import write_file

# 系统提示词：告诉模型它有三个工具可用
SYSTEM = (
    f"You are a coding agent working at {os.getcwd()}. "
    "Use the available tools to accomplish the user's task. Act, don't over-explain."
)

# 工具列表：比 s01 多了 read_file 和 write_file
TOOLS = [bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA]

# 工具处理函数映射：比 s01 多了两个 handler
HANDLERS = {
    "bash": bash.run,
    "read_file": read_file.run,
    "write_file": write_file.run,
}


def _print_tool_call(name: str, args: dict, output: str) -> None:
    """打印工具调用的可视化信息（黄色高亮）。

    为每个工具定制了展示格式：
    - bash: $ command（终端风格）
    - read_file: 📄 path
    - write_file: ✏️ path (N lines)
    """
    if name == "bash":
        print(f"\033[33m$ {args.get('command', '')}\033[0m")
    elif name == "read_file":
        path = args.get("file_path", "?")
        print(f"\033[33m[read_file] {path}\033[0m")
    elif name == "write_file":
        path = args.get("file_path", "?")
        content = args.get("content", "")
        lines = content.count("\n") + 1
        print(f"\033[33m[write_file] {path} ({lines} lines)\033[0m")
    else:
        print(f"\033[33m[{name}] {args}\033[0m")

    preview = output if len(output) < 400 else output[:400] + " ...(truncated)"
    print(preview)


def _print_assistant_text(messages: list) -> None:
    """打印模型最后的文本回复（绿色高亮）。"""
    last = messages[-1]
    if last.get("role") != "assistant":
        return
    text = last.get("content")
    if text and text.strip():
        print(f"\033[32m{text.strip()}\033[0m")


def main() -> None:
    """REPL 主循环：读取用户输入 → 调用 agent_loop → 打印结果。"""
    print("\033[36m== s02: Multi-Tool ==\033[0m  (q / exit 退出)")

    history: list = []

    while True:
        try:
            query = input("\033[36ms02 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if query.lower() in {"q", "exit", ""}:
            return

        history.append({"role": "user", "content": query})

        stop_reason = agent_loop(
            history,
            system=SYSTEM,
            tools=TOOLS,
            handlers=HANDLERS,
            on_tool_call=_print_tool_call,
        )

        _print_assistant_text(history)
        print(f"\033[90m[loop exit] stop_reason={stop_reason}  turns={_count_turns(history)}\033[0m\n")


def _count_turns(messages: list) -> int:
    """统计对话历史中有多少轮 assistant 消息。"""
    return sum(1 for m in messages if m.get("role") == "assistant")


if __name__ == "__main__":
    main()
