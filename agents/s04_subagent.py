#!/usr/bin/env python3
"""s04: Subagent —— 大任务拆小，每个小任务干净的上下文。

本文件在 s03 基础上新增 delegate 工具，让主 agent 能把子任务委托给
独立的子 agent 执行。子 agent 拥有全新的消息上下文，不会污染主对话。

新增机制：
- tools/subagent.py：delegate 工具，启动嵌套的 agent_loop
- 子 agent 可视化：缩进打印子 agent 的工具调用，区分主/子层级

运行方式：python agents/s04_subagent.py
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
from tools import subagent

# ---- 子 agent 可视化 ----


def _print_sub_tool_call(name: str, args: dict, output: str) -> None:
    """打印子 agent 的工具调用（缩进 + 灰色，区别于主 agent 的黄色）。

    用 "  >" 前缀和灰色（\033[90m）区分层级：
    - 主 agent 工具调用：黄色，无缩进
    - 子 agent 工具调用：灰色，缩进两格
    """
    if name == "bash":
        print(f"\033[90m  > $ {args.get('command', '')}\033[0m")
    elif name == "read_file":
        print(f"\033[90m  > [read_file] {args.get('file_path', '?')}\033[0m")
    elif name == "write_file":
        path = args.get("file_path", "?")
        lines = args.get("content", "").count("\n") + 1
        print(f"\033[90m  > [write_file] {path} ({lines} 行)\033[0m")
    else:
        print(f"\033[90m  > [{name}] {args}\033[0m")

    preview = output if len(output) < 300 else output[:300] + " ...（已截断）"
    print(f"  {preview}")


# 设置子 agent 的可视化回调
subagent.set_subagent_callback(_print_sub_tool_call)

# ---- 系统提示词 ----

# 原英文版：
# "You are a coding agent... Use the available tools... "
# "## Task Tracking (todo_write)... ## Delegation (delegate)..."
SYSTEM = (
    f"你是一个在 {os.getcwd()} 工作的编程助手。"
    "使用可用工具完成任务，直接行动，不要过度解释。\n\n"
    "## 任务追踪（todo_write）\n"
    "收到多步骤任务时：\n"
    "1. 先调用 todo_write 制定完整计划（所有项设为 'pending'）。\n"
    "2. 开始执行某项前，将其标记为 'in_progress'。\n"
    "3. 完成后标记为 'completed'。\n"
    "4. 每次调用都传入全部项（全量替换，非增量更新）。\n"
    "同一时刻只能有一项 'in_progress'。\n\n"
    "## 任务委托（delegate）\n"
    "当遇到可以独立完成的子任务时，用 delegate 委托给子 agent：\n"
    "- 子 agent 拥有全新的上下文，适合隔离执行\n"
    "- 子 agent 只能用 bash、read_file、write_file（不能再 delegate）\n"
    "- 在 task 参数中清楚描述要做什么即可"
)

# ---- 工具列表 ----

TOOLS = [
    bash.SCHEMA,
    read_file.SCHEMA,
    write_file.SCHEMA,
    todo.SCHEMA,
    subagent.SCHEMA,
]

# ---- Nag Wrapper（沿用 s03）----


def _make_nagging_handlers(base_handlers: dict) -> dict:
    """包装所有 handler，加入 nag 提醒机制。

    用闭包变量 tool_calls_since_todo 跟踪连续未调用 todo_write 的工具调用次数。
    超过阈值时，在工具输出末尾追加提醒文本。
    注意：这里统计的是"工具调用次数"而非"模型轮次"。
    """
    tool_calls_since_todo = [0]
    _NAG_THRESHOLD = 3

    def _wrap(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            result = fn(**kwargs)
            tool_calls_since_todo[0] += 1
            if tool_calls_since_todo[0] >= _NAG_THRESHOLD:
                reminder = (
                    f"\n\n[提醒] 你已经连续 {tool_calls_since_todo[0]} 次工具调用"
                    "没有更新待办列表了。考虑调用 todo_write 来追踪你的进度。"
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
    "delegate": subagent.run,
}

HANDLERS = _make_nagging_handlers(_BASE_HANDLERS)

# ---- 主 agent 可视化 ----


def _print_tool_call(name: str, args: dict, output: str) -> None:
    """打印主 agent 的工具调用（黄色高亮）。

    为 delegate 工具特别展示：显示被委托的任务和返回结果的摘要。
    """
    if name == "bash":
        print(f"\033[33m$ {args.get('command', '')}\033[0m")
    elif name == "read_file":
        path = args.get("file_path", "?")
        print(f"\033[33m[read_file] {path}\033[0m")
    elif name == "write_file":
        path = args.get("file_path", "?")
        lines = args.get("content", "").count("\n") + 1
        print(f"\033[33m[write_file] {path} ({lines} 行)\033[0m")
    elif name == "todo_write":
        items = args.get("items", [])
        counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for item in items:
            status = item.get("status", "pending")
            counts[status] = counts.get(status, 0) + 1
        parts = [f"{v} {k}" for k, v in counts.items() if v]
        print(f"\033[33m[todo_write] {len(items)} 项: {', '.join(parts)}\033[0m")
    elif name == "delegate":
        task = args.get("task", "?")
        # 截断过长的任务描述
        task_preview = task if len(task) < 80 else task[:80] + "..."
        print(f"\033[33m[delegate] 委托任务：{task_preview}\033[0m")
    else:
        print(f"\033[33m[{name}] {args}\033[0m")

    # delegate 的输出可能很长（子 agent 的完整结果），用较大阈值
    max_preview = 500 if name == "delegate" else 400
    if len(output) > max_preview:
        print(output[:max_preview] + " ...（已截断）")
    else:
        print(output)


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
    print("\033[36m== s04: Subagent ==\033[0m  (q / exit 退出)")

    history: list = []

    while True:
        try:
            query = input("\033[36ms04 >> \033[0m").strip()
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
            f"\033[90m[循环退出] stop_reason={stop_reason}  "
            f"turns={_count_turns(history)}\033[0m\n"
        )


if __name__ == "__main__":
    main()
