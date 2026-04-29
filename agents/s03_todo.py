#!/usr/bin/env python3
"""s03: TodoWrite —— 没有计划的 agent 走哪算哪。

本文件组装四个工具（bash / read_file / write_file / todo_write），
并用 handler wrapper 闭包实现 nag 提醒机制。

核心创新点：_make_nagging_handlers() 用闭包变量跟踪连续未调用 todo_write
的工具调用次数，超过阈值时在工具输出末尾追加提醒文本——完全不修改 core/loop.py。

运行方式：python agents/s03_todo.py
"""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.loop import agent_loop
from tools import bash
from tools import read_file
from tools import write_file
from tools import todo

# ---- 系统提示词 ----

# 原英文版：
# f"You are a coding agent working at {os.getcwd()}. "
# "Use the available tools to accomplish the user's task. Act, don't over-explain.\n\n"
# "## Task Tracking (todo_write)\n"
# "When given a multi-step task:\n"
# "1. First call todo_write with the full plan (all items as 'pending').\n"
# "2. Mark the current item as 'in_progress' before starting it.\n"
# "3. Mark items as 'completed' when done.\n"
# "4. Pass ALL items each time (full replacement, not incremental update).\n"
# "Only one item can be 'in_progress' at a time."
SYSTEM = (
    f"你是一个在 {os.getcwd()} 工作的编程助手。"
    "使用可用工具完成任务，直接行动，不要过度解释。\n\n"
    "## 任务追踪（todo_write）\n"
    "收到多步骤任务时：\n"
    "1. 先调用 todo_write 制定完整计划（所有项设为 'pending'）。\n"
    "2. 开始执行某项前，将其标记为 'in_progress'。\n"
    "3. 完成后标记为 'completed'。\n"
    "4. 每次调用都传入全部项（全量替换，非增量更新）。\n"
    "同一时刻只能有一项 'in_progress'。"
)

# ---- 工具列表 ----

TOOLS = [bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA, todo.SCHEMA]

# ---- Nag Wrapper（核心创新点）----


def _make_nagging_handlers(base_handlers: dict) -> dict:
    """包装所有 handler，加入 nag 提醒机制。

    用闭包变量 tool_calls_since_todo 跟踪连续未调用 todo_write 的工具调用次数。
    超过 _NAG_THRESHOLD 时，在工具输出末尾追加提醒文本。
    注意：这里统计的是"工具调用次数"而非"模型轮次"，
    如果同一轮模型并发调用多个工具，每个都会 +1。
    """
    tool_calls_since_todo = [0]  # 用 list 以便闭包修改
    _NAG_THRESHOLD = 3

    def _wrap(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            result = fn(**kwargs)
            tool_calls_since_todo[0] += 1
            if tool_calls_since_todo[0] >= _NAG_THRESHOLD:
                reminder = (
                    # "\n\n[REMINDER] You haven't updated your todo list in "
                    # "{N} tool calls. Consider calling todo_write to track your progress."
                    f"\n\n[提醒] 你已经连续 {tool_calls_since_todo[0]} 次工具调用没有更新待办列表了。"
                    "考虑调用 todo_write 来追踪你的进度。"
                )
                if todo.has_items():
                    reminder += "\n当前待办：\n" + todo.current()
                return result + reminder
            return result

        return wrapper

    def _todo_wrap(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            result = fn(**kwargs)
            tool_calls_since_todo[0] = 0  # 重置计数
            return result

        return wrapper

    wrapped = {}
    for name, handler in base_handlers.items():
        if name == "todo_write":
            wrapped[name] = _todo_wrap(handler)
        else:
            wrapped[name] = _wrap(handler)
    return wrapped


# ---- 基础 handlers + nag 包装 ----

_BASE_HANDLERS = {
    "bash": bash.run,
    "read_file": read_file.run,
    "write_file": write_file.run,
    "todo_write": todo.run,
}

HANDLERS = _make_nagging_handlers(_BASE_HANDLERS)

# ---- 可视化 ----


def _print_tool_call(name: str, args: dict, output: str) -> None:
    """打印工具调用的可视化信息（黄色高亮）。

    为每个工具定制了展示格式：
    - bash: $ command
    - read_file: [read_file] path
    - write_file: [write_file] path (N lines)
    - todo_write: [todo_write] 显示任务数和状态统计
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
        print(f"\033[33m[write_file] {path} ({lines} 行)\033[0m")
    elif name == "todo_write":
        items = args.get("items", [])
        counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for item in items:
            status = item.get("status", "pending")
            counts[status] = counts.get(status, 0) + 1
        parts = [f"{v} {k}" for k, v in counts.items() if v]
        print(f"\033[33m[todo_write] {len(items)} 项: {', '.join(parts)}\033[0m")
    else:
        print(f"\033[33m[{name}] {args}\033[0m")

    preview = output if len(output) < 400 else output[:400] + " ...（已截断）"
    print(preview)


def _print_assistant_text(messages: list) -> None:
    """打印模型最后的文本回复（绿色高亮）。"""
    last = messages[-1]
    if last.get("role") != "assistant":
        return
    text = last.get("content")
    if text and text.strip():
        print(f"\033[32m{text.strip()}\033[0m")


def _count_turns(messages: list) -> int:
    """统计对话历史中有多少轮 assistant 消息。"""
    return sum(1 for m in messages if m.get("role") == "assistant")


# ---- REPL ----


def main() -> None:
    """REPL 主循环：读取用户输入 → 调用 agent_loop → 打印结果。"""
    print("\033[36m== s03: TodoWrite ==\033[0m  (q / exit 退出)")

    history: list = []

    while True:
        try:
            query = input("\033[36ms03 >> \033[0m").strip()
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
        print(
            f"\033[90m[loop exit] stop_reason={stop_reason}  "
            f"turns={_count_turns(history)}\033[0m\n"
        )


if __name__ == "__main__":
    main()
