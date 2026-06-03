#!/usr/bin/env python3
"""s07: Task System —— 大目标要拆成小任务，记在磁盘上。

本文件在 s06 基础上用 tools/task 替代 tools/todo：
  - task_create: 增量创建任务，支持 parent_id 父子层级
  - task_update: 增量更新任务状态/描述
  - task_list:   查看/筛选任务
  - 持久化到 data/tasks.json，进程退出后任务不丢失

核心约束：core/loop.py 一行不改。

运行方式：python agents/s07_task_system.py
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
from tools import task
from tools import subagent
from tools import skill
from tools import compact

# ---- 子 agent 可视化 ----


def _print_sub_tool_call(name: str, args: dict, output: str) -> None:
    """打印子 agent 的工具调用（缩进 + 灰色，区别于主 agent 的黄色）。"""
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


subagent.set_subagent_callback(_print_sub_tool_call)

# ---- 系统提示词 ----

SYSTEM = (
    f"你是一个在 {os.getcwd()} 工作的编程助手。"
    "使用可用工具完成任务，直接行动，不要过度解释。\n\n"
    "## 任务追踪（task_create / task_update / task_list）\n"
    "收到多步骤任务时：\n"
    "1. 先调用 task_create 制定完整计划（所有项设为 'pending'）。\n"
    "   - 可以用 parent_id 把大任务拆成子任务（只支持一层）。\n"
    "2. 开始执行某项前，用 task_update 将其标记为 'in_progress'。\n"
    "3. 完成后用 task_update 标记为 'completed'。\n"
    "4. 同一时刻全局只能有一个 'in_progress'。\n"
    "5. 用 task_list 查看当前任务状态，支持按状态筛选。\n"
    "任务持久化到磁盘，进程退出后不会丢失。\n\n"
    "## 任务委托（delegate）\n"
    "当遇到可以独立完成的子任务时，用 delegate 委托给子 agent：\n"
    "- 子 agent 拥有全新的上下文，适合隔离执行\n"
    "- 子 agent 可用工具：bash、read_file、write_file、load_skill（不能再 delegate）\n"
    "- 在 task 参数中清楚描述要做什么即可\n\n"
    "## 技能加载（load_skill）\n"
    "遇到以下场景时，先调用 load_skill 加载相关技能：\n"
    "- 需要操作 git 时 → load_skill(\"git\")\n"
    "- 需要排查 bug 时 → load_skill(\"debug\")\n"
    "- 需要重构代码时 → load_skill(\"refactor\")\n"
    "加载后会获得专业知识和操作指引，然后按照指引执行任务。\n"
    "如果不确定有哪些技能，随便传一个名称，会返回可用列表。\n\n"
    "## 上下文压缩（compact）\n"
    "系统会自动压缩旧的工具输出（micro_compact）并在上下文过长时自动摘要（auto_compact）。\n"
    "当你感觉对话历史冗余、模型似乎遗忘早期信息时，也可以主动调用 compact 手动触发压缩。"
)

# ---- 工具列表 ----

TOOLS = [
    bash.SCHEMA,
    read_file.SCHEMA,
    write_file.SCHEMA,
    task.SCHEMA_CREATE,
    task.SCHEMA_UPDATE,
    task.SCHEMA_LIST,
    subagent.SCHEMA,
    skill.SCHEMA,
    compact.SCHEMA,
]

# ---- Nag Wrapper（适配 task 工具）----


def _make_nagging_handlers(base_handlers: dict) -> dict:
    """包装所有 handler，加入 nag 提醒机制。

    task_create / task_update / task_list 重置计数器；
    compact 不计入计数；其余正常计数。
    """
    tool_calls_since_task = [0]
    _NAG_THRESHOLD = 3

    def _wrap(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            result = fn(**kwargs)
            tool_calls_since_task[0] += 1
            if tool_calls_since_task[0] >= _NAG_THRESHOLD:
                reminder = (
                    f"\n\n[提醒] 你已经连续 {tool_calls_since_task[0]} 次工具调用"
                    "没有更新任务列表了。考虑调用 task_create 或 task_update 来追踪你的进度。"
                )
                reminder += "\n当前任务：\n" + task.current()
                return result + reminder
            return result

        return wrapper

    def _task_wrap(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            result = fn(**kwargs)
            tool_calls_since_task[0] = 0
            return result

        return wrapper

    wrapped = {}
    for name, handler in base_handlers.items():
        if name in ("task_create", "task_update", "task_list"):
            wrapped[name] = _task_wrap(handler)
        elif name == "compact":
            wrapped[name] = handler
        else:
            wrapped[name] = _wrap(handler)
    return wrapped


# ---- 基础 handlers + nag 包装 ----

_BASE_HANDLERS = {
    "bash": bash.run,
    "read_file": read_file.run,
    "write_file": write_file.run,
    "task_create": task.create,
    "task_update": task.update,
    "task_list": task.list_tasks,
    "delegate": subagent.run,
    "load_skill": skill.run,
    "compact": compact.run,
}

HANDLERS = _make_nagging_handlers(_BASE_HANDLERS)

# ---- 主 agent 可视化 ----


def _print_tool_call(name: str, args: dict, output: str) -> None:
    """打印主 agent 的工具调用（黄色高亮）。"""
    if name == "bash":
        print(f"\033[33m$ {args.get('command', '')}\033[0m")
    elif name == "read_file":
        path = args.get("file_path", "?")
        print(f"\033[33m[read_file] {path}\033[0m")
    elif name == "write_file":
        path = args.get("file_path", "?")
        lines = args.get("content", "").count("\n") + 1
        print(f"\033[33m[write_file] {path} ({lines} 行)\033[0m")
    elif name == "task_create":
        tasks_list = args.get("tasks", [])
        parts = []
        for t in tasks_list:
            txt = t.get("text", "")
            pid = t.get("parent_id")
            label = txt if len(txt) < 40 else txt[:40] + "..."
            if pid:
                parts.append(f"{label} (→ {pid})")
            else:
                parts.append(label)
        print(f"\033[33m[task_create] {len(tasks_list)} 项: {', '.join(parts)}\033[0m")
    elif name == "task_update":
        updates_list = args.get("updates", [])
        parts = []
        for u in updates_list:
            tid = u.get("id", "?")
            status = u.get("status", "")
            parts.append(f"#{tid}" + (f"→{status}" if status else ""))
        print(f"\033[33m[task_update] {', '.join(parts)}\033[0m")
    elif name == "task_list":
        status = args.get("status", "all")
        print(f"\033[33m[task_list] 筛选: {status}\033[0m")
    elif name == "delegate":
        task_desc = args.get("task", "?")
        task_preview = task_desc if len(task_desc) < 80 else task_desc[:80] + "..."
        print(f"\033[33m[delegate] 委托任务：{task_preview}\033[0m")
    elif name == "load_skill":
        skill_name = args.get("name", "?")
        print(f"\033[33m[load_skill] 加载技能：{skill_name}\033[0m")
    elif name == "compact":
        print(f"\033[33m[compact] 手动触发上下文压缩\033[0m")
    else:
        print(f"\033[33m[{name}] {args}\033[0m")

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


# ---- 压缩集成回调 ----


def _make_compacting_callback(messages: list):
    """创建带压缩逻辑的 on_tool_call 回调。

    通过 closure 持有 messages 引用，在每次工具调用后
    执行 micro_compact + 检查 auto_compact。
    """
    def callback(name, args, output):
        _print_tool_call(name, args, output)
        compact.check_and_compact(messages)
    return callback


# ---- REPL ----


def main() -> None:
    """REPL 主循环。"""
    print("\033[36m== s07: Task System ==\033[0m  (q / exit 退出)")

    history: list = []
    on_tool_call = _make_compacting_callback(history)

    while True:
        try:
            query = input("\033[36ms07 >> \033[0m").strip()
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
            on_tool_call=on_tool_call,
        )

        _print_assistant_text(history)
        print(
            f"\033[90m[循环退出] stop_reason={stop_reason}  "
            f"turns={_count_turns(history)}\033[0m\n"
        )


if __name__ == "__main__":
    main()
