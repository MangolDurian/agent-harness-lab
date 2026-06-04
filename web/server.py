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
from tools import bash, read_file, write_file, todo, task, subagent, skill, compact, background

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

    return stages


STAGES = _build_stages()
DEFAULT_STAGE = "s08"


# ---- Background Wrapper（s08+）----


def _make_background_handlers(base_handlers: dict, bg_manager) -> dict:
    """包装所有 handler：bash+run_in_background 走后台线程，所有 handler 前缀后台通知。"""
    import functools as _ft

    def wrap(name, handler):
        @_ft.wraps(handler)
        def wrapper(**kwargs):
            notifications = ""
            completed = bg_manager.collect()
            if completed:
                notifications = bg_manager.format_results(completed) + "\n\n"

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

        event_queue.put(event)

        if stage_cfg["use_compact"]:
            compact.check_and_compact(messages)

    def on_sub_tool_call(name: str, args: dict, output: str):
        event = {"type": "sub_tool_call", "name": name, "args": args, "output": output}
        event_queue.put(event)

    if stage_cfg["use_subagent"]:
        subagent.set_subagent_callback(on_sub_tool_call)

    handlers = dict(stage_cfg["handlers"])

    # s08+: background wrapper 先于 nag
    if stage_cfg.get("use_background"):
        handlers = _make_background_handlers(handlers, background)

    if stage_cfg["use_nag"]:
        handlers = _make_nagging_handlers(handlers, stage_cfg["use_compact"])

    # Post-loop flush：模型不再调工具后，检查是否有后台任务完成通知
    while True:
        stop_reason = agent_loop(
            messages,
            system=stage_cfg["system"],
            tools=stage_cfg["tools"],
            handlers=handlers,
            on_tool_call=on_tool_call,
        )

        if not stage_cfg.get("use_background"):
            break

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
            continue

        # 还有在跑的任务？短超时轮询等收尾
        if background.has_running():
            deadline = time.time() + 10
            while background.has_running() and time.time() < deadline:
                time.sleep(0.2)
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
