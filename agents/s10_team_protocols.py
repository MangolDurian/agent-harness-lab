#!/usr/bin/env python3
"""s10: Team Protocols —— 队友之间要有统一的沟通规矩。

本文件在 s09 基础上增加结构化协议机制：
  - shutdown_request / shutdown_response：优雅关机握手替代 __shutdown__ 强杀
  - plan_submit / plan_review：高风险操作审批门控
  - list_requests：查看所有协议请求状态
  - 每个协议请求带唯一 req_id，响应引用同一 ID（请求-响应配对）

核心设计：
  - ProtocolTracker：追踪两类协议请求，FSM pending → approved/rejected
  - 结构化消息：send() 支持 msg_type + metadata，inbox 格式化感知协议类型
  - 队友工具扩展：通过 configure_teammate 注入 shutdown_response 和 plan_submit

核心约束：core/loop.py 一行不改。

运行方式：python agents/s10_team_protocols.py
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
from tools import skill
from tools import compact
from tools import background
from tools import team
from tools import protocols

# 初始化团队管理器（在 .team/ 目录下）
team.init()

# 配置队友的额外工具（协议工具 + system prompt 后缀）
_team_manager = team.get_manager()
_team_manager.configure_teammate(
    extra_tools=[protocols.SCHEMA_SHUTDOWN_RESPONSE, protocols.SCHEMA_PLAN_SUBMIT],
    handler_factories={
        "shutdown_response": protocols.make_shutdown_response_handler,
        "plan_submit": protocols.make_plan_submit_handler,
    },
    system_suffix=(
        "\n\n## 团队协议\n"
        "- 收到 shutdown_request 时，使用 shutdown_response(request_id, approve, reason) 响应\n"
        "  - approve=true：收尾工作并退出\n"
        "  - approve=false：拒绝关机，继续工作\n"
        "- 遇到高风险操作时（如删除文件、重构核心代码），先用 plan_submit(plan) 提交计划\n"
        "  - 等待 lead 审批后再执行\n"
        "  - 如果计划被拒绝，调整方案后重新提交或放弃"
    ),
)

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
    "## 团队协议（shutdown_request / shutdown_response / plan_submit / plan_review / list_requests）\n"
    "结构化请求-响应协议，替代随意消息：\n\n"
    "### 关机协议\n"
    "- shutdown_request(name)：请求队友优雅关机，队友会收到请求并用 shutdown_response 响应\n"
    "- 队友响应后你可以看到批准/拒绝结果\n"
    "- 不要直接用 __shutdown__ 杀队友\n\n"
    "### 计划审批协议\n"
    "- 队友收到高风险任务时会用 plan_submit 提交计划\n"
    "- 你需要用 plan_review(request_id, approve, feedback) 审批\n"
    "- approve=true 队友开始执行，approve=false 队友调整计划或放弃\n\n"
    "### 查看协议状态\n"
    "- list_requests()：查看所有协议请求\n\n"
    "## 团队协作（spawn / send / broadcast / team_status）\n"
    "任务太大一个人干不完时，用队友分工：\n"
    "- spawn(name, role, prompt)：创建队友并分配任务，队友在后台独立工作\n"
    "- send(to, content)：给指定队友发消息（追加消息/追加工单）\n"
    "- broadcast(content)：给所有队友广播消息\n"
    "- team_status()：查看团队状态（谁在忙、谁空闲）\n"
    "队友完成后会自动通知你，通知会在下一次工具调用时出现。\n"
    "可以同时创建多个队友并发干活，不必等一个完成再创建下一个。\n\n"
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
    team.SCHEMA_SPAWN,
    team.SCHEMA_SEND,
    team.SCHEMA_BROADCAST,
    team.SCHEMA_STATUS,
    protocols.SCHEMA_SHUTDOWN_REQUEST,
    protocols.SCHEMA_PLAN_REVIEW,
    protocols.SCHEMA_LIST_REQUESTS,
    background.SCHEMA_STATUS,
    skill.SCHEMA,
    compact.SCHEMA,
]

# ---- Background + Team + Protocol handler wrapper ----


def _make_background_handlers(base_handlers: dict, bg_manager, team_manager) -> dict:
    """包装所有 handler：bash+run_in_background 走后台线程，所有 handler 前缀通知。

    参数：
        base_handlers: 原始 handler 映射
        bg_manager: BackgroundManager 实例
        team_manager: TeammateManager 实例
    """

    def wrap(name, handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            # 1. 收集已完成的后台任务 + 队友消息，拼接到输出前面
            notifications = ""

            # 后台任务完成通知
            completed = bg_manager.collect()
            if completed:
                notifications += bg_manager.format_results(completed) + "\n\n"

            # 队友 inbox 消息（格式化协议消息）
            inbox = team_manager.read_inbox("lead")
            formatted_inbox = team.format_inbox(inbox)
            if formatted_inbox:
                notifications += "[队友消息]\n" + formatted_inbox + "\n\n"

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


# ---- Nag Wrapper ----


def _make_nagging_handlers(base_handlers: dict) -> dict:
    """包装所有 handler，加入 nag 提醒机制。"""
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
    "spawn": team.spawn,
    "send": team.send,
    "broadcast": team.broadcast,
    "team_status": team.team_status,
    "shutdown_request": protocols.shutdown_request,
    "plan_review": protocols.plan_review,
    "list_requests": protocols.list_requests,
    "load_skill": skill.run,
    "compact": compact.run,
    "background_status": background.status,
}

# 组装顺序：background(+team inbox) → nag
_bg_handlers = _make_background_handlers(_BASE_HANDLERS, background, _team_manager)
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
    elif name == "spawn":
        _name = args.get("name", "?")
        _role = args.get("role", "?")
        print(f"\033[33m[spawn] 创建队友：{_name}（{_role}）\033[0m")
    elif name == "send":
        _to = args.get("to", "?")
        _content = args.get("content", "")
        preview = _content if len(_content) < 60 else _content[:60] + "..."
        print(f"\033[33m[send] 发给 {_to}: {preview}\033[0m")
    elif name == "broadcast":
        _content = args.get("content", "")
        preview = _content if len(_content) < 60 else _content[:60] + "..."
        print(f"\033[33m[broadcast] {preview}\033[0m")
    elif name == "team_status":
        print(f"\033[33m[team_status] 查看团队状态\033[0m")
    elif name == "shutdown_request":
        _target = args.get("name", "?")
        print(f"\033[33m[shutdown_request] 请求关机: {_target}\033[0m")
    elif name == "plan_review":
        _req_id = args.get("request_id", "?")
        _approve = args.get("approve", False)
        status = "批准" if _approve else "拒绝"
        print(f"\033[33m[plan_review] #{_req_id} {status}\033[0m")
    elif name == "list_requests":
        print(f"\033[33m[list_requests] 查看协议请求\033[0m")
    elif name == "load_skill":
        skill_name = args.get("name", "?")
        print(f"\033[33m[load_skill] 加载技能：{skill_name}\033[0m")
    elif name == "compact":
        print(f"\033[33m[compact] 手动触发上下文压缩\033[0m")
    elif name == "background_status":
        print(f"\033[33m[background_status] 查询后台任务状态\033[0m")
    else:
        print(f"\033[33m[{name}] {args}\033[0m")

    max_preview = 500 if name == "spawn" else 400
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
    """创建带压缩逻辑的 on_tool_call 回调。"""
    def callback(name, args, output):
        _print_tool_call(name, args, output)
        compact.check_and_compact(messages)
    return callback


# ---- REPL ----


def main() -> None:
    """REPL 主循环。"""
    print("\033[36m== s10: Team Protocols ==\033[0m  (q / exit 退出)")

    history: list = []
    on_tool_call = _make_compacting_callback(history)

    try:
        while True:
            try:
                query = input("\033[36ms10 >> \033[0m").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if query.lower() in {"q", "exit", ""}:
                return

            history.append({"role": "user", "content": query})

            # 内循环：agent_loop 退出后检查通知
            while True:
                stop_reason = agent_loop(
                    history,
                    system=SYSTEM,
                    tools=TOOLS,
                    handlers=HANDLERS,
                    on_tool_call=on_tool_call,
                )

                # Post-loop flush：检查后台任务 + 队友消息
                completed = background.collect()
                inbox = _team_manager.read_inbox("lead")
                formatted_inbox = team.format_inbox(inbox)
                has_notifications = bool(completed) or bool(formatted_inbox)

                if has_notifications:
                    notification_parts = []
                    if completed:
                        notification_parts.append(
                            f"[系统] 后台任务完成通知：\n{background.format_results(completed)}"
                        )
                    if formatted_inbox:
                        notification_parts.append(
                            f"[队友消息]\n{formatted_inbox}"
                        )
                    history.append({
                        "role": "user",
                        "content": "\n\n".join(notification_parts),
                    })
                    print(f"\033[36m[通知注入，通知模型]\033[0m")
                    continue

                # 还有在跑的后台任务或队友？短超时等收尾
                has_running = background.has_running() or _team_manager.has_working_teammates()
                if has_running:
                    deadline = time.time() + 15
                    while time.time() < deadline:
                        time.sleep(0.5)
                        # 优先检查队友消息（先于后台任务）
                        inbox = _team_manager.read_inbox("lead")
                        formatted_inbox = team.format_inbox(inbox)
                        if formatted_inbox:
                            notification_parts = [f"[队友消息]\n{formatted_inbox}"]
                            completed = background.collect()
                            if completed:
                                notification_parts.insert(
                                    0,
                                    f"[系统] 后台任务完成通知：\n{background.format_results(completed)}",
                                )
                            history.append({
                                "role": "user",
                                "content": "\n\n".join(notification_parts),
                            })
                            print(f"\033[36m[通知注入，通知模型]\033[0m")
                            break
                        # 再检查后台任务
                        completed = background.collect()
                        if completed:
                            notification = background.format_results(completed)
                            history.append({
                                "role": "user",
                                "content": f"[系统] 后台任务完成通知：\n{notification}",
                            })
                            print(f"\033[36m[后台任务完成，通知模型]\033[0m")
                            break
                    else:
                        # 超时了但还在跑，不再等，让用户下次交互时处理
                        pass
                    # 如果上面的 while-break 路径注入了通知，继续 loop
                    if formatted_inbox or completed:
                        continue

                break

            # 防：break 前最后兜底——队友可能在 has_working 检查和 break 之间完成
            final_inbox = _team_manager.read_inbox("lead")
            final_formatted = team.format_inbox(final_inbox)
            final_bg = background.collect()
            if final_formatted or final_bg:
                notification_parts = []
                if final_bg:
                    notification_parts.append(
                        f"[系统] 后台任务完成通知：\n{background.format_results(final_bg)}"
                    )
                if final_formatted:
                    notification_parts.append(f"[队友消息]\n{final_formatted}")
                history.append({
                    "role": "user",
                    "content": "\n\n".join(notification_parts),
                })
                print(f"\033[36m[兜底通知注入，通知模型]\033[0m")
                # 跑一轮让模型处理
                agent_loop(
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
    finally:
        # 退出时清理队友线程（兜底：仍有存活的队友用 shutdown_all 强退）
        team.shutdown_all()
        print("\033[90m[已通知所有队友停止]\033[0m")


if __name__ == "__main__":
    main()
