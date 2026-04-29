"""todo 工具 —— agent 的任务追踪器。

让 agent 能记录待办事项、追踪进度，配合 nag 提醒机制防止忘记做计划。
采用全量替换模式：每次调用都传入完整的 todo 列表。
"""
from __future__ import annotations


class TodoManager:
    """管理 todo 列表：全量替换、状态查询、格式化输出。"""

    def __init__(self) -> None:
        self._items: list[dict] = []

    def replace(self, items: list[dict]) -> str:
        """全量替换 todo 列表。

        验证每项都有 text，分配 id，检查只有一个 in_progress。
        """
        if not items:
            self._items = []
            # Todo list cleared.
            return "待办列表已清空。"

        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = item.get("text", "").strip()
            if not text:
                # Error: item {i + 1} has empty text.
                return f"错误：第 {i + 1} 项的描述为空。"
            status = item.get("status", "pending")
            if status not in ("pending", "in_progress", "completed"):
                # Error: item {i + 1} has invalid status '{status}'.
                return f"错误：第 {i + 1} 项的状态 '{status}' 无效。"
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": str(i + 1), "text": text, "status": status})

        if in_progress_count > 1:
            # Error: only one item can be 'in_progress' at a time.
            return "错误：同一时刻只能有一项 'in_progress'。"

        self._items = validated
        return self.format()

    def format(self) -> str:
        """格式化为可读的 todo 列表字符串，用于 nag 提醒和工具输出。"""
        if not self._items:
            # (no todos)
            return "（无待办事项）"

        status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        lines = []
        for item in self._items:
            icon = status_icon.get(item["status"], "[?]")
            lines.append(f"  {item['id']}. {icon} {item['text']}")

        summary = self._summary()
        return "\n".join(lines) + f"\n{summary}"

    def has_in_progress(self) -> bool:
        """是否有 in_progress 的任务（用于 nag 判断）。"""
        return any(item["status"] == "in_progress" for item in self._items)

    def _summary(self) -> str:
        """生成状态统计摘要。"""
        counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for item in self._items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        parts = []
        if counts["pending"]:
            parts.append(f"{counts['pending']} 待办")
        if counts["in_progress"]:
            parts.append(f"{counts['in_progress']} 进行中")
        if counts["completed"]:
            parts.append(f"{counts['completed']} 已完成")
        return f"({', '.join(parts)})"


# ---- 模块级单例 + SCHEMA + run ----

_manager = TodoManager()

SCHEMA = {
    "type": "function",
    "function": {
        "name": "todo_write",
        # "Update the todo list. Pass ALL items each time (full replacement). "
        # "Only one item can be 'in_progress'. Use this to plan and track your progress."
        "description": (
            "更新待办列表。每次调用都传入完整列表（全量替换）。"
            "同一时刻只能有一项 'in_progress'。用此工具来规划和追踪进度。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                # "Description of the task"
                                "description": "任务描述",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                        },
                        "required": ["text", "status"],
                    },
                    # "Complete list of todo items. Replaces the entire list each call."
                    "description": "完整的待办事项列表，每次调用都会替换整个列表。",
                }
            },
            "required": ["items"],
        },
    },
}


def run(items: list[dict]) -> str:
    """全量替换 todo 列表并返回格式化的当前状态。"""
    return _manager.replace(items)


def current() -> str:
    """返回格式化的当前 todo 列表（供外部读取，不修改状态）。"""
    return _manager.format()


def has_items() -> bool:
    """当前 todo 列表是否非空。"""
    return bool(_manager._items)
