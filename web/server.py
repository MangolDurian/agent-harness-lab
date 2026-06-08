#!/usr/bin/env python3
"""Web 调试前端 —— FastAPI WebSocket 服务器。

在浏览器中实时展示 agent 的工具调用、todo 状态、子 agent 层级等信息。
通过 threading + queue 桥接同步的 agent_loop 到 async WebSocket。
支持前端切换 s01~s06 不同阶段。

运行方式：
    source .venv/bin/activate
    pip install fastapi uvicorn websockets
    python web/server.py
    # 浏览器打开 http://localhost:8765
"""
from __future__ import annotations

import asyncio
import functools
import json
import sys
import threading
import time
from pathlib import Path
from queue import Queue, Empty

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from core.loop import agent_loop
from tools import bash, read_file, write_file, todo, task, subagent, skill, compact, background, team, protocols

# ---- Stage Registry（s01 ~ s06 逐层叠加）----


def _build_stages() -> dict:
    """构建阶段配置注册表。每个阶段在前一阶段基础上叠加新能力。"""
    base = f"你是一个在 {Path.cwd()} 工作的编程助手。"

    # SYSTEM prompt 各段落
    _bash_only = "使用 bash 工具完成任务，直接行动，不要过度解释。"
    _multi_tool = "使用可用工具完成任务，直接行动，不要过度解释。"
    _todo = (
        "\n\n## 任务追踪（todo_write）\n"
        "收到多步骤任务时：\n"
        "1. 先调用 todo_write 制定完整计划（所有项设为 'pending'）。\n"
        "2. 开始执行某项前，将其标记为 'in_progress'。\n"
        "3. 完成后标记为 'completed'。\n"
        "4. 每次调用都传入全部项（全量替换，非增量更新）。\n"
        "同一时刻只能有一项 'in_progress'。"
    )
    _delegate = (
        "\n\n## 任务委托（delegate）\n"
        "当遇到可以独立完成的子任务时，用 delegate 委托给子 agent：\n"
        "- 子 agent 拥有全新的上下文，适合隔离执行\n"
        "- 子 agent 可用工具：bash、read_file、write_file、load_skill（不能再 delegate）\n"
        "- 在 task 参数中清楚描述要做什么即可"
    )
    _skill = (
        "\n\n## 技能加载（load_skill）\n"
        "遇到以下场景时，先调用 load_skill 加载相关技能：\n"
        '- 需要操作 git 时 → load_skill("git")\n'
        '- 需要排查 bug 时 → load_skill("debug")\n'
        '- 需要重构代码时 → load_skill("refactor")\n'
        "加载后会获得专业知识和操作指引，然后按照指引执行任务。\n"
        "如果不确定有哪些技能，随便传一个名称，会返回可用列表。"
    )
    _compact = (
        "\n\n## 上下文压缩（compact）\n"
        "系统会自动压缩旧的工具输出（micro_compact）并在上下文过长时自动摘要（auto_compact）。\n"
        "当你感觉对话历史冗余、模型似乎遗忘早期信息时，也可以主动调用 compact 手动触发压缩。"
    )

    stages = {}

    # s01: bash only
    stages["s01"] = {
        "tag": "s01 Agent Loop",
        "system": base + _bash_only,
        "tools": [bash.SCHEMA],
        "handlers": {"bash": bash.run},
        "use_nag": False,
        "use_subagent": False,
        "use_compact": False,
    }

    # s02: + read_file, write_file
    stages["s02"] = {
        "tag": "s02 Multi Tool",
        "system": base + _multi_tool,
        "tools": [bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA],
        "handlers": {
            "bash": bash.run,
            "read_file": read_file.run,
            "write_file": write_file.run,
        },
        "use_nag": False,
        "use_subagent": False,
        "use_compact": False,
    }

    # s03: + todo + nag
    stages["s03"] = {
        "tag": "s03 TodoWrite",
        "system": base + _multi_tool + _todo,
        "tools": [bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA, todo.SCHEMA],
        "handlers": {
            "bash": bash.run,
            "read_file": read_file.run,
            "write_file": write_file.run,
            "todo_write": todo.run,
        },
        "use_nag": True,
        "use_subagent": False,
        "use_compact": False,
    }

    # s04: + subagent
    stages["s04"] = {
        "tag": "s04 Subagent",
        "system": base + _multi_tool + _todo + _delegate,
        "tools": [
            bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA,
            todo.SCHEMA, subagent.SCHEMA,
        ],
        "handlers": {
            "bash": bash.run,
            "read_file": read_file.run,
            "write_file": write_file.run,
            "todo_write": todo.run,
            "delegate": subagent.run,
        },
        "use_nag": True,
        "use_subagent": True,
        "use_compact": False,
    }

    # s05: + skill
    stages["s05"] = {
        "tag": "s05 Skills",
        "system": base + _multi_tool + _todo + _delegate + _skill,
        "tools": [
            bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA,
            todo.SCHEMA, subagent.SCHEMA, skill.SCHEMA,
        ],
        "handlers": {
            "bash": bash.run,
            "read_file": read_file.run,
            "write_file": write_file.run,
            "todo_write": todo.run,
            "delegate": subagent.run,
            "load_skill": skill.run,
        },
        "use_nag": True,
        "use_subagent": True,
        "use_compact": False,
    }

    # s06: + compact
    stages["s06"] = {
        "tag": "s06 Context Compact",
        "system": base + _multi_tool + _todo + _delegate + _skill + _compact,
        "tools": [
            bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA,
            todo.SCHEMA, subagent.SCHEMA, skill.SCHEMA, compact.SCHEMA,
        ],
        "handlers": {
            "bash": bash.run,
            "read_file": read_file.run,
            "write_file": write_file.run,
            "todo_write": todo.run,
            "delegate": subagent.run,
            "load_skill": skill.run,
            "compact": compact.run,
        },
        "use_nag": True,
        "use_subagent": True,
        "use_compact": True,
    }

    _task = (
        "\n\n## 任务追踪（task_create / task_update / task_list）\n"
        "收到多步骤任务时：\n"
        "1. 先调用 task_create 制定完整计划（所有项设为 'pending'）。\n"
        "   - 可以用 parent_id 把大任务拆成子任务（只支持一层）。\n"
        "2. 开始执行某项前，用 task_update 将其标记为 'in_progress'。\n"
        "3. 完成后用 task_update 标记为 'completed'。\n"
        "4. 同一时刻全局只能有一个 'in_progress'。\n"
        "5. 用 task_list 查看当前任务状态，支持按状态筛选。\n"
        "任务持久化到磁盘，进程退出后不会丢失。"
    )

    # s07: + task system (replaces todo with persistent tasks)
    stages["s07"] = {
        "tag": "s07 Task System",
        "system": base + _multi_tool + _task + _delegate + _skill + _compact,
        "tools": [
            bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA,
            task.SCHEMA_CREATE, task.SCHEMA_UPDATE, task.SCHEMA_LIST,
            subagent.SCHEMA, skill.SCHEMA, compact.SCHEMA,
        ],
        "handlers": {
            "bash": bash.run,
            "read_file": read_file.run,
            "write_file": write_file.run,
            "task_create": task.create,
            "task_update": task.update,
            "task_list": task.list_tasks,
            "delegate": subagent.run,
            "load_skill": skill.run,
            "compact": compact.run,
        },
        "use_nag": True,
        "use_subagent": True,
        "use_compact": True,
    }

    _background = (
        "\n\n## 后台任务（bash run_in_background + background_status）\n"
        "长时间运行的命令（pip install、docker build、npm install 等），"
        "在 bash 调用时设 run_in_background=true，命令会在后台执行。\n"
        "设为 true 后你会立刻收到「后台任务已启动」的回复，可以继续做其他事。\n"
        "后台任务完成后，结果会出现在下一次工具调用的输出中。\n"
        "如果你想主动检查后台任务状态，调用 background_status 即可。\n"
        "用户问你「装好了吗」时，用 background_status 确认而不是凭记忆回答。"
    )

    import copy as _copy
    _SCHEMA_BASH_BG = _copy.deepcopy(bash.SCHEMA)
    _SCHEMA_BASH_BG["function"]["parameters"]["properties"]["run_in_background"] = {
        "type": "boolean",
        "description": "是否在后台运行（慢命令如 pip install、npm install、docker build 推荐设为 true）",
    }

    # s08: + background tasks
    stages["s08"] = {
        "tag": "s08 Background Tasks",
        "system": base + _multi_tool + _background + _task + _delegate + _skill + _compact,
        "tools": [
            _SCHEMA_BASH_BG, read_file.SCHEMA, write_file.SCHEMA,
            task.SCHEMA_CREATE, task.SCHEMA_UPDATE, task.SCHEMA_LIST,
            subagent.SCHEMA, skill.SCHEMA, compact.SCHEMA,
            background.SCHEMA_STATUS,
        ],
        "handlers": {
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
        },
        "use_nag": True,
        "use_subagent": True,
        "use_compact": True,
        "use_background": True,
    }

    _team = (
        "\n\n## 团队协作（spawn / send / broadcast / team_status）\n"
        "任务太大一个人干不完时，用队友分工：\n"
        "- spawn(name, role, prompt)：创建队友并分配任务，队友在后台独立工作\n"
        "- send(to, content)：给指定队友发消息\n"
        "- broadcast(content)：给所有队友广播消息\n"
        "- team_status()：查看团队状态\n"
        "队友完成后会自动通知你。\n"
        "可以同时创建多个队友并发干活。"
    )

    # s09: + agent teams (spawn replaces delegate)
    stages["s09"] = {
        "tag": "s09 Agent Teams",
        "system": base + _multi_tool + _background + _team + _task + _skill + _compact,
        "tools": [
            _SCHEMA_BASH_BG, read_file.SCHEMA, write_file.SCHEMA,
            task.SCHEMA_CREATE, task.SCHEMA_UPDATE, task.SCHEMA_LIST,
            team.SCHEMA_SPAWN, team.SCHEMA_SEND, team.SCHEMA_BROADCAST, team.SCHEMA_STATUS,
            background.SCHEMA_STATUS, skill.SCHEMA, compact.SCHEMA,
        ],
        "handlers": {
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
            "load_skill": skill.run,
            "compact": compact.run,
            "background_status": background.status,
        },
        "use_nag": True,
        "use_subagent": False,
        "use_compact": True,
        "use_background": True,
        "use_team": True,
    }

    _protocols = (
        "\n\n## 团队协议（shutdown_request / plan_review / list_requests）\n"
        "结构化请求-响应协议，替代随意消息：\n"
        "- shutdown_request(name)：请求队友优雅关机\n"
        "- plan_review(request_id, approve, feedback)：审批队友计划\n"
        "- list_requests()：查看所有协议请求\n"
        "队友会用 plan_submit 提交高风险操作计划，等待你审批。"
    )

    # s10: + team protocols
    stages["s10"] = {
        "tag": "s10 Team Protocols",
        "system": base + _multi_tool + _background + _team + _protocols + _task + _skill + _compact,
        "tools": [
            _SCHEMA_BASH_BG, read_file.SCHEMA, write_file.SCHEMA,
            task.SCHEMA_CREATE, task.SCHEMA_UPDATE, task.SCHEMA_LIST,
            team.SCHEMA_SPAWN, team.SCHEMA_SEND, team.SCHEMA_BROADCAST, team.SCHEMA_STATUS,
            protocols.SCHEMA_SHUTDOWN_REQUEST, protocols.SCHEMA_PLAN_REVIEW, protocols.SCHEMA_LIST_REQUESTS,
            background.SCHEMA_STATUS, skill.SCHEMA, compact.SCHEMA,
        ],
        "handlers": {
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
        },
        "use_nag": True,
        "use_subagent": False,
        "use_compact": True,
        "use_background": True,
        "use_team": True,
        "use_protocols": True,
    }

    _autonomous = (
        "\n\n## 自主认领（s11 新增）\n"
        "队友空闲时会自动扫描任务板，发现无主 pending 任务会自己认领并执行。\n"
        "你不需要手动分配任务给队友——只要创建了任务，空闲队友会自动认领。\n"
        "队友认领后任务会显示 @队友名 标记，你可以用 task_list 查看。\n"
        "队友空闲 60 秒无工作会自动退出。"
    )

    # s11: + autonomous agents
    stages["s11"] = {
        "tag": "s11 Autonomous Agents",
        "system": base + _multi_tool + _background + _team + _protocols + _autonomous + _task + _skill + _compact,
        "tools": [
            _SCHEMA_BASH_BG, read_file.SCHEMA, write_file.SCHEMA,
            task.SCHEMA_CREATE, task.SCHEMA_UPDATE, task.SCHEMA_LIST,
            team.SCHEMA_SPAWN, team.SCHEMA_SEND, team.SCHEMA_BROADCAST, team.SCHEMA_STATUS,
            protocols.SCHEMA_SHUTDOWN_REQUEST, protocols.SCHEMA_PLAN_REVIEW, protocols.SCHEMA_LIST_REQUESTS,
            background.SCHEMA_STATUS, skill.SCHEMA, compact.SCHEMA,
        ],
        "handlers": {
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
        },
        "use_nag": True,
        "use_subagent": False,
        "use_compact": True,
        "use_background": True,
        "use_team": True,
        "use_protocols": True,
        "use_autonomous": True,
    }

    return stages


STAGES = _build_stages()
DEFAULT_STAGE = "s11"


# ---- Background Wrapper（s08+）----


def _make_background_handlers(base_handlers: dict, bg_manager, team_manager=None, use_protocols=False) -> dict:
    """包装所有 handler：bash+run_in_background 走后台线程，所有 handler 前缀后台通知 + 队友 inbox。"""
    import functools as _ft

    def wrap(name, handler):
        @_ft.wraps(handler)
        def wrapper(**kwargs):
            notifications = ""
            completed = bg_manager.collect()
            if completed:
                notifications = bg_manager.format_results(completed) + "\n\n"

            # s09: drain lead inbox
            if team_manager:
                inbox = team_manager.read_inbox("lead")
                # s10: format protocol messages nicely
                if use_protocols:
                    formatted = team.format_inbox(inbox)
                else:
                    formatted = inbox if inbox != "[]" else ""
                if formatted:
                    notifications += "[队友消息]\n" + formatted + "\n\n"

            if name == "bash" and kwargs.get("run_in_background"):
                kwargs.pop("run_in_background", None)
                command = kwargs.get("command", "")
                bg_id = bg_manager.start(lambda: handler(**kwargs), command)
                return (
                    notifications
                    + f"后台任务 bg_{bg_id} 已启动，命令：{command}\n"
                    "完成时会通知你。你可以继续做其他事。"
                )

            kwargs.pop("run_in_background", None)
            return notifications + handler(**kwargs)
        return wrapper

    return {name: wrap(name, h) for name, h in base_handlers.items()}


# ---- Nag Wrapper（支持 stage 差异化）----


def _make_nagging_handlers(base_handlers: dict, use_compact: bool = False) -> dict:
    """包装所有 handler，加入 nag 提醒机制。

    todo_write 重置计数器；compact（如果存在）不计入计数；其余正常计数。
    """
    tool_calls_since_todo = [0]
    _NAG_THRESHOLD = 3
    # s07 起任务工具换成 task_*，提醒文案与数据源也要随之切换
    uses_task = "task_create" in base_handlers

    def _wrap(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            result = fn(**kwargs)
            tool_calls_since_todo[0] += 1
            if tool_calls_since_todo[0] >= _NAG_THRESHOLD:
                if uses_task:
                    reminder = (
                        f"\n\n[提醒] 你已经连续 {tool_calls_since_todo[0]} 次工具调用"
                        "没有更新任务列表了。考虑调用 task_create 或 task_update 来追踪你的进度。"
                    )
                    reminder += "\n当前任务：\n" + task.current()
                else:
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
            tool_calls_since_todo[0] = 0
            return result

        return wrapper

    wrapped = {}
    for name, handler in base_handlers.items():
        if name in ("todo_write", "task_create", "task_update", "task_list"):
            wrapped[name] = _todo_wrap(handler)
        elif name == "compact":
            wrapped[name] = handler  # compact 不计入 nag 计数
        else:
            wrapped[name] = _wrap(handler)
    return wrapped


# ---- WebSocket 事件桥接 ----


def _run_agent_in_thread(
    messages: list,
    event_queue: Queue,
    stage_cfg: dict,
):
    """在子线程中运行 agent_loop，通过 queue 推送事件。"""

    def on_tool_call(name: str, args: dict, output: str):
        event = {"type": "tool_call", "name": name, "args": args, "output": output}

        if name == "todo_write":
            event["todo_state"] = args.get("items", [])
        elif name in ("task_create", "task_update", "task_list"):
            event["task_state"] = task.current()

        # s08: 检测后台任务启动和完成
        if args.get("run_in_background"):
            event["background_start"] = True
        if output and "[后台任务 bg_" in output:
            event["background_complete"] = True

        # s09: 检测队友消息注入
        if output and "[队友消息]" in output:
            event["team_message"] = True

        # s10: 检测协议事件
        if name in ("shutdown_request", "shutdown_response",
                     "plan_submit", "plan_review", "list_requests"):
            event["protocol_event"] = True
            if name == "shutdown_request":
                event["protocol_type"] = "shutdown_request"
                event["protocol_target"] = args.get("name", "?")
            elif name == "shutdown_response":
                event["protocol_type"] = "shutdown_response"
                event["protocol_req_id"] = args.get("request_id", "?")
                event["protocol_approved"] = args.get("approve", False)
            elif name == "plan_submit":
                event["protocol_type"] = "plan_submit"
                event["protocol_plan_preview"] = (args.get("plan", "") or "")[:80]
            elif name == "plan_review":
                event["protocol_type"] = "plan_review"
                event["protocol_req_id"] = args.get("request_id", "?")
                event["protocol_approved"] = args.get("approve", False)
            elif name == "list_requests":
                event["protocol_type"] = "list_requests"
            # 发送当前协议状态快照
            if stage_cfg.get("use_protocols"):
                event["protocol_state"] = protocols._tracker.list_requests()

        event_queue.put(event)

        if stage_cfg["use_compact"]:
            compact.check_and_compact(messages)

    def on_sub_tool_call(name: str, args: dict, output: str):
        event = {"type": "sub_tool_call", "name": name, "args": args, "output": output}
        event_queue.put(event)

    if stage_cfg["use_subagent"]:
        subagent.set_subagent_callback(on_sub_tool_call)

    handlers = dict(stage_cfg["handlers"])

    # s09: init team manager
    team_manager = None
    if stage_cfg.get("use_team"):
        team.init()
        team_manager = team.get_manager()
        # s10: configure teammates with protocol tools
        if stage_cfg.get("use_protocols"):
            extra_tools_list = [protocols.SCHEMA_SHUTDOWN_RESPONSE, protocols.SCHEMA_PLAN_SUBMIT]
            handler_factories_map = {
                "shutdown_response": protocols.make_shutdown_response_handler,
                "plan_submit": protocols.make_plan_submit_handler,
            }
            system_suffix_text = (
                "\n\n## 团队协议\n"
                "- 收到 shutdown_request 时，使用 shutdown_response(request_id, approve, reason) 响应\n"
                "  - approve=true：收尾工作并退出\n"
                "  - approve=false：拒绝关机，继续工作\n"
                "- 遇到高风险操作时（如删除文件、重构核心代码），先用 plan_submit(plan) 提交计划\n"
                "  - 等待 lead 审批后再执行\n"
                "  - 如果计划被拒绝，调整方案后重新提交或放弃"
            )
            # s11: add task tools for teammates
            if stage_cfg.get("use_autonomous"):
                extra_tools_list += [task.SCHEMA_LIST, task.SCHEMA_CLAIM, task.SCHEMA_COMPLETE]
                handler_factories_map["task_list"] = lambda name: task.list_tasks
                handler_factories_map["task_claim"] = task.make_claim_handler
                handler_factories_map["task_complete"] = task.make_complete_handler
                system_suffix_text += (
                    "\n\n## 自主认领\n"
                    "- 你空闲时会自动扫描任务板，发现无主 pending 任务会通知你\n"
                    "- 用 task_claim(task_id) 认领任务，认领后用 task_complete(task_id) 完成它\n"
                    "- 同一时间你只能有一个 in_progress 任务\n"
                    "- 完成任务后通过 send 向 lead 汇报"
                )
                team_manager.configure_autonomous(enabled=True, timeout=60.0)
            team_manager.configure_teammate(
                extra_tools=extra_tools_list,
                handler_factories=handler_factories_map,
                system_suffix=system_suffix_text,
            )

    # s08+: background wrapper 先于 nag
    if stage_cfg.get("use_background"):
        handlers = _make_background_handlers(handlers, background, team_manager,
                                              use_protocols=stage_cfg.get("use_protocols", False))

    if stage_cfg["use_nag"]:
        handlers = _make_nagging_handlers(handlers, stage_cfg["use_compact"])

    # Post-loop flush：模型不再调工具后，检查是否有后台任务完成通知 + 队友消息
    while True:
        stop_reason = agent_loop(
            messages,
            system=stage_cfg["system"],
            tools=stage_cfg["tools"],
            handlers=handlers,
            on_tool_call=on_tool_call,
        )

        if not stage_cfg.get("use_background") and not stage_cfg.get("use_team"):
            break

        notification_parts = []

        # 后台任务完成通知
        completed = background.collect()
        if completed:
            notification_parts.append(
                f"[系统] 后台任务完成通知：\n{background.format_results(completed)}"
            )

        # s09: 队友 inbox 消息
        team_inbox_raw = "[]"
        if team_manager:
            team_inbox_raw = team_manager.read_inbox("lead")

        has_notifications = bool(completed) or team_inbox_raw != "[]"

        if has_notifications:
            if team_inbox_raw != "[]":
                if stage_cfg.get("use_protocols"):
                    formatted = team.format_inbox(team_inbox_raw)
                    notification_parts.append(f"[队友消息]\n{formatted}" if formatted else "")
                else:
                    notification_parts.append(f"[队友消息]\n{team_inbox_raw}")
            notification_parts = [p for p in notification_parts if p]
            messages.append({
                "role": "user",
                "content": "\n\n".join(notification_parts),
            })
            event_queue.put({
                "type": "system_message",
                "text": "通知注入，通知模型处理",
            })
            continue

        # 还有在跑的后台任务或工作中的队友？短超时轮询等收尾
        has_running = background.has_running()
        has_working = team_manager and team_manager.has_working_teammates()
        if has_running or has_working:
            deadline = time.time() + 15
            while time.time() < deadline:
                time.sleep(0.5)
                # 优先检查队友消息
                if team_manager:
                    team_inbox_raw = team_manager.read_inbox("lead")
                    if team_inbox_raw != "[]":
                        notification_parts = []
                        if stage_cfg.get("use_protocols"):
                            formatted = team.format_inbox(team_inbox_raw)
                            if formatted:
                                notification_parts.append(f"[队友消息]\n{formatted}")
                        else:
                            notification_parts.append(f"[队友消息]\n{team_inbox_raw}")
                        completed = background.collect()
                        if completed:
                            notification_parts.insert(
                                0,
                                f"[系统] 后台任务完成通知：\n{background.format_results(completed)}",
                            )
                        notification_parts = [p for p in notification_parts if p]
                        if notification_parts:
                            messages.append({
                                "role": "user",
                                "content": "\n\n".join(notification_parts),
                            })
                            event_queue.put({
                                "type": "system_message",
                                "text": "通知注入，通知模型处理",
                            })
                            break
                # 再检查后台任务
                completed = background.collect()
                if completed:
                    notification = background.format_results(completed)
                    messages.append({
                        "role": "user",
                        "content": f"[系统] 后台任务完成通知：\n{notification}",
                    })
                    event_queue.put({
                        "type": "system_message",
                        "text": "后台任务完成，通知模型处理",
                    })
                    break
            else:
                # 超时了但还在跑，不再等
                pass
            # 兜底：超时等待期间队友/后台可能在检查和 break 之间完成
            final_inbox = team_manager.read_inbox("lead") if team_manager else "[]"
            final_bg = background.collect()
            if final_inbox != "[]" or final_bg:
                notification_parts = []
                if final_bg:
                    notification_parts.append(
                        f"[系统] 后台任务完成通知：\n{background.format_results(final_bg)}"
                    )
                if final_inbox != "[]":
                    if stage_cfg.get("use_protocols"):
                        formatted = team.format_inbox(final_inbox)
                        if formatted:
                            notification_parts.append(f"[队友消息]\n{formatted}")
                    else:
                        notification_parts.append(f"[队友消息]\n{final_inbox}")
                notification_parts = [p for p in notification_parts if p]
                if notification_parts:
                    messages.append({
                        "role": "user",
                        "content": "\n\n".join(notification_parts),
                    })
                    event_queue.put({
                        "type": "system_message",
                        "text": "兜底通知注入，通知模型处理",
                    })
                    continue

        break

    assistant_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            text = msg["content"].strip()
            if text:
                assistant_text = text
                break

    turn_count = sum(1 for m in messages if m.get("role") == "assistant")

    event_queue.put({
        "type": "processing_end",
        "assistant_text": assistant_text,
        "turn_count": turn_count,
        "stop_reason": stop_reason,
    })
    event_queue.put(None)  # sentinel: 表示 agent 运行结束


# ---- FastAPI 应用 ----

app = FastAPI()

HTML_PATH = Path(__file__).resolve().parent / "index.html"


@app.get("/")
async def index():
    return FileResponse(HTML_PATH)


@app.get("/api/stages")
async def stages_api():
    """返回可用阶段列表和默认阶段。"""
    return {
        "stages": [{"id": k, "tag": v["tag"]} for k, v in STAGES.items()],
        "default": DEFAULT_STAGE,
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    messages: list = []
    current_stage = DEFAULT_STAGE

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            # ---- 切换阶段 ----
            if data.get("type") == "switch_stage":
                stage_id = data.get("stage", DEFAULT_STAGE)
                if stage_id in STAGES:
                    current_stage = stage_id
                    messages = []
                    compact.reset_state()
                    event = {
                        "type": "stage_switched",
                        "stage": stage_id,
                        "tag": STAGES[stage_id]["tag"],
                    }
                    # s07: 加载已有任务状态
                    if stage_id == "s07":
                        event["task_state"] = task.current()
                    elif stage_id == "s08":
                        event["task_state"] = task.current()
                        background.reset()
                    elif stage_id == "s09":
                        event["task_state"] = task.current()
                        background.reset()
                        team.reset()
                    elif stage_id == "s10":
                        event["task_state"] = task.current()
                        background.reset()
                        team.reset()
                        protocols.reset()
                    elif stage_id == "s11":
                        event["task_state"] = task.current()
                        background.reset()
                        team.reset()
                        protocols.reset()
                    await ws.send_text(json.dumps(event, ensure_ascii=False))
                continue

            # ---- 用户消息 ----
            if data.get("type") != "user_message":
                continue

            user_text = data.get("content", "").strip()
            if not user_text:
                continue

            stage_cfg = STAGES[current_stage]
            messages.append({"role": "user", "content": user_text})

            await ws.send_text(json.dumps({"type": "processing_start"}))

            event_queue: Queue = Queue()
            thread = threading.Thread(
                target=_run_agent_in_thread,
                args=(messages, event_queue, stage_cfg),
                daemon=True,
            )
            thread.start()

            while True:
                try:
                    event = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: event_queue.get(timeout=0.1)
                    )
                except Empty:
                    if not thread.is_alive():
                        break
                    continue

                if event is None:
                    break

                await ws.send_text(json.dumps(event, ensure_ascii=False))

            thread.join(timeout=1)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    print("Agent Harness Debugger → http://localhost:8765")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
