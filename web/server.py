#!/usr/bin/env python3
"""Web 调试前端 —— FastAPI WebSocket 服务器。

在浏览器中实时展示 agent 的工具调用、todo 状态、子 agent 层级等信息。
通过 threading + queue 桥接同步的 agent_loop 到 async WebSocket。

运行方式：
    source .venv/bin/activate
    pip install fastapi uvicorn websockets
    python web/server.py
    # 浏览器打开 http://localhost:8765
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from queue import Queue, Empty

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from core.loop import agent_loop
from tools import bash, read_file, write_file, todo, subagent, skill
import functools

# ---- 复用 s05 的配置（不复制代码，直接导入） ----

SYSTEM = (
    f"你是一个在 {Path.cwd()} 工作的编程助手。"
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
    "- 在 task 参数中清楚描述要做什么即可\n\n"
    "## 技能加载（load_skill）\n"
    "遇到以下场景时，先调用 load_skill 加载相关技能：\n"
    "- 需要操作 git 时 → load_skill(\"git\")\n"
    "- 需要排查 bug 时 → load_skill(\"debug\")\n"
    "- 需要重构代码时 → load_skill(\"refactor\")\n"
    "加载后会获得专业知识和操作指引，然后按照指引执行任务。\n"
    "如果不确定有哪些技能，随便传一个名称，会返回可用列表。"
)

TOOLS = [
    bash.SCHEMA,
    read_file.SCHEMA,
    write_file.SCHEMA,
    todo.SCHEMA,
    subagent.SCHEMA,
    skill.SCHEMA,
]

_BASE_HANDLERS = {
    "bash": bash.run,
    "read_file": read_file.run,
    "write_file": write_file.run,
    "todo_write": todo.run,
    "delegate": subagent.run,
    "load_skill": skill.run,
}


# ---- Nag Wrapper（从 s05 复用） ----


def _make_nagging_handlers(base_handlers: dict) -> dict:
    """包装所有 handler，加入 nag 提醒机制。"""
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
            tool_calls_since_todo[0] = 0
            return result

        return wrapper

    wrapped = {}
    for name, handler in base_handlers.items():
        if name == "todo_write":
            wrapped[name] = _todo_wrap(handler)
        else:
            wrapped[name] = _wrap(handler)
    return wrapped


# ---- WebSocket 事件桥接 ----

# 使用 queue + threading 把同步 agent_loop 桥接到 async WebSocket
# agent_loop 在子线程运行，通过 queue 发送事件
# 主线程的 async handler 从 queue 取事件推送到 WebSocket


def _run_agent_in_thread(
    messages: list,
    event_queue: Queue,
):
    """在子线程中运行 agent_loop，通过 queue 推送事件。"""

    def on_tool_call(name: str, args: dict, output: str):
        event = {"type": "tool_call", "name": name, "args": args, "output": output}

        # 拦截 todo_write 参数，附带当前 todo 状态
        if name == "todo_write":
            event["todo_state"] = args.get("items", [])

        event_queue.put(event)

    def on_sub_tool_call(name: str, args: dict, output: str):
        event = {"type": "sub_tool_call", "name": name, "args": args, "output": output}
        event_queue.put(event)

    # 设置子 agent 回调
    subagent.set_subagent_callback(on_sub_tool_call)

    handlers = _make_nagging_handlers(_BASE_HANDLERS)

    stop_reason = agent_loop(
        messages,
        system=SYSTEM,
        tools=TOOLS,
        handlers=handlers,
        on_tool_call=on_tool_call,
    )

    # 提取最后的 assistant 文本
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


# ---- 版本标识 ----

VERSION_TAG = "s05 Skills"


# ---- FastAPI 应用 ----

app = FastAPI()

HTML_PATH = Path(__file__).resolve().parent / "index.html"


@app.get("/")
async def index():
    return FileResponse(HTML_PATH)


@app.get("/api/version")
async def version():
    return {"tag": VERSION_TAG}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    messages: list = []

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            if data.get("type") != "user_message":
                continue

            user_text = data.get("content", "").strip()
            if not user_text:
                continue

            messages.append({"role": "user", "content": user_text})

            # 通知前端：开始处理
            await ws.send_text(json.dumps({"type": "processing_start"}))

            # 在子线程运行 agent_loop
            event_queue: Queue = Queue()
            thread = threading.Thread(
                target=_run_agent_in_thread,
                args=(messages, event_queue),
                daemon=True,
            )
            thread.start()

            # 从 queue 读取事件并推送到 WebSocket
            while True:
                # 用 run_in_executor 避免阻塞事件循环
                try:
                    event = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: event_queue.get(timeout=0.1)
                    )
                except Empty:
                    # 检查线程是否还在运行
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
