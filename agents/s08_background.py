#!/usr/bin/env python3
"""s08: Background Tasks —— 慢操作丢后台，agent 继续想下一步。

本文件在 s07 基础上增加后台任务机制：
  - bash 工具新增 run_in_background 参数
  - 设为 true 时，命令在后台线程执行，agent 立即获得回复
  - 后台任务完成后，结果通过 handler wrapper 注入到下一次工具输出中

核心约束：core/loop.py 一行不改。

运行方式：python agents/s08_background.py
"""
from __future__ import annotations

import copy
import functools
import os
import sys
import time
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
from tools import background

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

# ---- 扩展 bash SCHEMA（加 run_in_background 参数）----

SCHEMA_BASH_BG = copy.deepcopy(bash.SCHEMA)
SCHEMA_BASH_BG["function"]["parameters"]["properties"]["run_in_background"] = {
    "type": "boolean",
    "description": "是否在后台运行（慢命令如 pip install、npm install、docker build 推荐设为 true）",
}

# ---- 系统提示词 ----

SYSTEM = (
    f"你是一个在 {os.getcwd()} 工作的编程助手。"
    "使用可用工具完成任务，直接行动，不要过度解释。\n\n"
    "## 后台任务（bash run_in_background + background_status）\n"
    "长时间运行的命令（pip install、docker build、npm install 等），"
    "在 bash 调用时设 run_in_background=true，命令会在后台执行。\n"
    "设为 true 后你会立刻收到「后台任务已启动」的回复，可以继续做其他事。\n"
    "后台任务完成后，结果会出现在下一次工具调用的输出中。\n"
    "如果你想主动检查后台任务状态，调用 background_status 即可。\n"
    "用户问你「装好了吗」时，用 background_status 确认而不是凭记忆回答。\n\n"
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
    SCHEMA_BASH_BG,
    read_file.SCHEMA,
    write_file.SCHEMA,
    task.SCHEMA_CREATE,
    task.SCHEMA_UPDATE,
    task.SCHEMA_LIST,
    subagent.SCHEMA,
    skill.SCHEMA,
    compact.SCHEMA,
    background.SCHEMA_STATUS,
]

# ---- Background handler wrapper ----


def _make_background_handlers(base_handlers: dict, bg_manager) -> dict:
    """包装所有 handler：bash+run_in_background 走后台线程，所有 handler 前缀后台通知。

    参数：
        base_handlers: 原始 handler 映射
        bg_manager: BackgroundManager 实例

    返回：
        包装后的 handler 映射
    """

    def wrap(name, handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            # 1. 收集已完成的后台任务，拼接到输出前面
            notifications = ""
            completed = bg_manager.collect()
            if completed:
                notifications = bg_manager.format_results(completed) + "\n\n"

            # 2. bash + run_in_background → 后台线程
            if name == "bash" and kwargs.get("run_in_background"):
                kwargs.pop("run_in_background", None)
                command = kwargs.get("command", "")
                bg_id = bg_manager.start(lambda: handler(**kwargs), command)
                return (
                    notifications
                    + f"后台任务 bg_{bg_id} 已启动，命令：{command}\n"
                    "完成时会通知你。你可以继续做其他事。"
                )

            # 3. 弹出 run_in_background（如果 bash 没设为 true）
            kwargs.pop("run_in_background", None)

            # 4. 正常执行
            return notifications + handler(**kwargs)

        return wrapper

    return {name: wrap(name, h) for name, h in base_handlers.items()}


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


# ---- 基础 handlers + background + nag 包装 ----

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
    "background_status": background.status,
}

# 组装顺序：background → nag
_bg_handlers = _make_background_handlers(_BASE_HANDLERS, background)
HANDLERS = _make_nagging_handlers(_bg_handlers)

# ---- 主 agent 可视化 ----


def _print_tool_call(name: str, args: dict, output: str) -> None:
    """打印主 agent 的工具调用（黄色高亮）。"""
    if name == "bash" and args.get("run_in_background"):
        print(f"\033[33m$ {args.get('command', '')} [background]\033[0m")
    elif name == "bash":
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
    elif name == "background_status":
        print(f"\033[33m[background_status] 查询后台任务状态\033[0m")
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
    print("\033[36m== s08: Background Tasks ==\033[0m  (q / exit 退出)")

    history: list = []
    on_tool_call = _make_compacting_callback(history)

    while True:
        try:
            query = input("\033[36ms08 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if query.lower() in {"q", "exit", ""}:
            return

        history.append({"role": "user", "content": query})

        # 内循环：agent_loop 退出后检查是否有后台任务完成通知需要 flush
        # - 已完成的任务：注入 user 消息，再跑一轮 loop
        # - 还在跑的任务：短超时轮询等它收尾（最多 10 秒）
        # - 两轮 flush 之间如果又冒出新完成通知，继续 flush（不做轮数硬上限）
        while True:
            stop_reason = agent_loop(
                history,
                system=SYSTEM,
                tools=TOOLS,
                handlers=HANDLERS,
                on_tool_call=on_tool_call,
            )

            # Post-loop flush：检查已完成的后台任务
            completed = background.collect()
            if completed:
                notification = background.format_results(completed)
                history.append({
                    "role": "user",
                    "content": f"[系统] 后台任务完成通知：\n{notification}",
                })
                print(f"\033[36m[后台任务完成，通知模型]\033[0m")
                continue  # 再跑一轮 loop，让模型处理通知

            # 还有在跑的任务？短超时轮询等收尾
            if background.has_running():
                deadline = time.time() + 10
                while background.has_running() and time.time() < deadline:
                    time.sleep(0.2)
                completed = background.collect()
                if completed:
                    notification = background.format_results(completed)
                    history.append({
                        "role": "user",
                        "content": f"[系统] 后台任务完成通知：\n{notification}",
                    })
                    print(f"\033[36m[后台任务完成，通知模型]\033[0m")
                    continue

            break

        _print_assistant_text(history)
        print(
            f"\033[90m[循环退出] stop_reason={stop_reason}  "
            f"turns={_count_turns(history)}\033[0m\n"
        )


if __name__ == "__main__":
    main()
