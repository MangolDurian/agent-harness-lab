"""background 工具 —— 后台任务管理器。

让 agent 把慢命令（pip install、docker build 等）丢到后台线程执行，
自己继续干别的事，后台完成后再通过 handler wrapper 注入结果通知。

核心机制：
  - BackgroundManager: 线程安全的后台任务管理器
  - start(func, command): 在 daemon 线程中执行 func，立即返回 bg_id
  - collect(): 返回并清除所有已完成的任务
  - handler wrapper 在每次工具调用前收集通知，拼接到输出前面
"""
from __future__ import annotations

import threading


class BackgroundManager:
    """线程安全的后台任务管理器。"""

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}  # bg_id -> {status, output, command}
        self._next_id: int = 1
        self._lock = threading.Lock()

    def start(self, func, command: str = "") -> str:
        """在 daemon 线程中执行 func，立即返回 bg_id。

        参数：
            func: 无参可调用对象，返回字符串结果
            command: 命令描述，用于通知中展示

        返回：
            bg_id 字符串（如 "1"、"2"）
        """
        with self._lock:
            bg_id = str(self._next_id)
            self._next_id += 1
            self._tasks[bg_id] = {
                "status": "running",
                "output": None,
                "command": command,
            }

        def _run():
            try:
                result = func()
                with self._lock:
                    self._tasks[bg_id]["status"] = "completed"
                    self._tasks[bg_id]["output"] = result
            except Exception as e:
                with self._lock:
                    self._tasks[bg_id]["status"] = "failed"
                    self._tasks[bg_id]["output"] = str(e)

        threading.Thread(target=_run, daemon=True).start()
        return bg_id

    def collect(self) -> list[dict]:
        """返回并清除所有已完成的任务。

        返回：
            已完成任务列表，每项含 bg_id、status、output、command
        """
        with self._lock:
            completed = []
            remaining = {}
            for bg_id, info in self._tasks.items():
                if info["status"] != "running":
                    completed.append({
                        "bg_id": bg_id,
                        "status": info["status"],
                        "output": info["output"],
                        "command": info["command"],
                    })
                else:
                    remaining[bg_id] = info
            self._tasks = remaining
            return completed

    def has_running(self) -> bool:
        """是否有正在运行的后台任务。"""
        with self._lock:
            return any(t["status"] == "running" for t in self._tasks.values())

    def running_tasks(self) -> list[dict]:
        """返回正在运行的任务信息（不修改状态）。"""
        with self._lock:
            return [
                {"bg_id": bg_id, "command": info["command"]}
                for bg_id, info in self._tasks.items()
                if info["status"] == "running"
            ]

    def format_results(self, results: list[dict]) -> str:
        """格式化完成通知文本。

        参数：
            results: collect() 返回的已完成任务列表

        返回：
            格式化的通知文本，例如：
            [后台任务 bg_1 完成] sleep 3 && echo done
            done

            [后台任务 bg_2 失败] some_command
            错误信息...
        """
        parts = []
        for r in results:
            header = f"[后台任务 bg_{r['bg_id']} "
            if r["status"] == "completed":
                header += "完成"
            else:
                header += "失败"
            header += "]"

            if r["command"]:
                header += f" {r['command']}"

            section = header
            if r["output"]:
                section += "\n" + r["output"]
            parts.append(section)

        return "\n\n".join(parts)


# ---- 模块级单例 + 函数 ----

_manager = BackgroundManager()


def start(func, command: str = "") -> str:
    """在后台线程执行 func，返回 bg_id。"""
    return _manager.start(func, command)


def collect() -> list[dict]:
    """返回并清除所有已完成的后台任务。"""
    return _manager.collect()


def has_running() -> bool:
    """是否有正在运行的后台任务。"""
    return _manager.has_running()


def running_tasks() -> list[dict]:
    """返回正在运行的任务信息。"""
    return _manager.running_tasks()


def format_results(results: list[dict]) -> str:
    """格式化后台任务完成通知。"""
    return _manager.format_results(results)


SCHEMA_STATUS = {
    "type": "function",
    "function": {
        "name": "background_status",
        "description": "查看后台任务的运行状态。用于检查之前启动的后台命令是否完成。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


def status() -> str:
    """返回当前后台任务状态摘要。

    注意：已完成的任务通知由 handler wrapper 的 collect() 自动注入到输出前缀，
    本函数只负责展示还在运行中的任务。
    """
    running = _manager.running_tasks()
    if not running:
        return "没有正在运行的后台任务。"
    lines = [f"bg_{t['bg_id']}: 运行中 - {t['command']}" for t in running]
    return "\n".join(lines) + f"\n（共 {len(running)} 个后台任务运行中）"


def reset() -> None:
    """清空所有后台任务（仅用于测试/重置）。"""
    with _manager._lock:
        _manager._tasks.clear()
        _manager._next_id = 1
