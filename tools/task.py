"""task 工具 —— 持久化任务管理系统。

替代 todo.py 的全量替换模式，提供三个增量工具：
  - task_create: 批量创建任务（支持 parent_id 父子层级）
  - task_update: 批量更新任务状态/文本
  - task_list:   查看/筛选任务

持久化到 data/tasks.json，进程退出后任务不丢失。
采用原子写入（.tmp → rename）保证崩溃安全。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STORAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "tasks.json"


class TaskManager:
    """管理持久化任务：创建、更新、查看，支持单层父子层级。"""

    def __init__(self, storage_path: Path) -> None:
        self._tasks: dict[str, dict] = {}  # id -> task
        self._next_id: int = 1
        self._path = storage_path
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        """从磁盘加载任务数据，文件不存在则初始化为空。"""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._tasks = data.get("tasks", {})
            self._next_id = data.get("next_id", 1)
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self) -> None:
        """原子写入：先写 .tmp 再 rename，防止写到一半崩溃丢失数据。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"next_id": self._next_id, "tasks": self._tasks}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ---- 工具方法 ----

    def create(self, tasks: list[dict]) -> str:
        """批量创建任务，返回格式化树。

        先全量校验，全部合法才提交（错误时不修改任何状态，真正的整体回滚）。
        """
        if not tasks:
            return "错误：tasks 不能为空。"

        now = datetime.now(timezone.utc).isoformat()
        errors = []
        validated = []  # 通过校验的任务字段（尚未写入）
        new_in_progress = 0

        for i, item in enumerate(tasks):
            text = item.get("text", "").strip()
            if not text:
                errors.append(f"第 {i + 1} 项描述为空")
                continue

            parent_id = item.get("parent_id")
            if parent_id is not None:
                parent_id = str(parent_id)
                if parent_id not in self._tasks:
                    errors.append(f"第 {i + 1} 项的 parent_id '{parent_id}' 不存在")
                    continue
                # 只允许一层：parent 必须是根任务
                if self._tasks[parent_id].get("parent_id") is not None:
                    errors.append(f"第 {i + 1} 项的 parent_id '{parent_id}' 不是根任务，不支持嵌套子任务")
                    continue

            status = item.get("status", "pending")
            if status not in ("pending", "in_progress", "completed"):
                errors.append(f"第 {i + 1} 项的状态 '{status}' 无效")
                continue

            if status == "in_progress":
                new_in_progress += 1
            validated.append({"text": text, "status": status, "parent_id": parent_id})

        # 全局只能有一个 in_progress：已有的 + 本批新增的
        existing_in_progress = sum(
            1 for t in self._tasks.values() if t["status"] == "in_progress"
        )
        if existing_in_progress + new_in_progress > 1:
            errors.append("全局只能有一个 'in_progress' 任务")

        if errors:
            return "错误：" + "；".join(errors) + "。"

        # 校验全部通过，统一提交
        for fields in validated:
            tid = str(self._next_id)
            self._next_id += 1
            self._tasks[tid] = {
                "id": tid,
                "text": fields["text"],
                "status": fields["status"],
                "parent_id": fields["parent_id"],
                "created_at": now,
                "updated_at": now,
            }

        self._save()
        return self.format()

    def update(self, updates: list[dict]) -> str:
        """批量更新任务，返回格式化树。

        先全量校验（含全局单 in_progress 约束），全部合法才提交，
        错误时不修改任何任务状态（真正的整体回滚）。
        """
        if not updates:
            return "错误：updates 不能为空。"

        errors = []
        now = datetime.now(timezone.utc).isoformat()
        # 收集待应用的变更（尚未写入）：tid -> {status?, text?}
        planned: dict[str, dict] = {}

        for i, item in enumerate(updates):
            tid = str(item.get("id", ""))
            if tid not in self._tasks:
                errors.append(f"第 {i + 1} 项 id '{tid}' 不存在")
                continue

            change: dict = {}

            new_status = item.get("status")
            if new_status is not None:
                if new_status not in ("pending", "in_progress", "completed"):
                    errors.append(f"第 {i + 1} 项状态 '{new_status}' 无效")
                    continue
                change["status"] = new_status

            new_text = item.get("text")
            if new_text is not None:
                new_text = new_text.strip()
                if not new_text:
                    errors.append(f"第 {i + 1} 项描述为空")
                    continue
                change["text"] = new_text

            if change:
                planned[tid] = {**planned.get(tid, {}), **change}

        if not planned and not errors:
            return "错误：没有有效的更新。"

        # 基于"变更后"的状态校验全局只能有一个 in_progress
        in_progress = 0
        for tid, task in self._tasks.items():
            final_status = planned.get(tid, {}).get("status", task["status"])
            if final_status == "in_progress":
                in_progress += 1
        if in_progress > 1:
            errors.append("全局只能有一个 'in_progress' 任务")

        if errors:
            return "错误：" + "；".join(errors) + "。"

        # 校验全部通过，统一提交
        for tid, change in planned.items():
            task = self._tasks[tid]
            if "status" in change:
                task["status"] = change["status"]
            if "text" in change:
                task["text"] = change["text"]
            task["updated_at"] = now

        self._save()
        return self.format()

    def list_tasks(self, status: str | None = None) -> str:
        """查看任务，可选按状态筛选。"""
        return self.format(status)

    # ---- 格式化 & 辅助 ----

    def format(self, status_filter: str | None = None) -> str:
        """树形渲染任务列表。

        每行以真实任务 id 开头（'#3'），父子关系用缩进体现，
        例如：
            #1 [ ] 搭建 Web API
              #6 [ ] 设计数据库 schema
        显示的 '#id' 就是 task_update / parent_id 要用的 id（不再用易混淆的 1.1 序号）。
        """
        if not self._tasks:
            return "（无任务）"

        # 收集根任务
        roots = [t for t in self._tasks.values() if t.get("parent_id") is None]
        roots.sort(key=lambda t: int(t["id"]))

        lines = []
        for root in roots:
            # 收集子任务
            children = [
                t for t in self._tasks.values()
                if t.get("parent_id") == root["id"]
            ]
            children.sort(key=lambda t: int(t["id"]))

            # 如果有状态筛选，检查根+子是否匹配
            if status_filter:
                root_match = root["status"] == status_filter
                child_match = [c for c in children if c["status"] == status_filter]
                if not root_match and not child_match:
                    continue
                if root_match:
                    lines.append(self._format_task(root))
                for child in child_match:
                    lines.append(self._format_task(child, indent=True))
            else:
                lines.append(self._format_task(root))
                for child in children:
                    lines.append(self._format_task(child, indent=True))

        if not lines:
            if status_filter:
                return f"（没有 '{status_filter}' 状态的任务）"
            return "（无任务）"

        summary = self._summary()
        return "\n".join(lines) + f"\n{summary}"

    def _format_task(self, task: dict, indent: bool = False) -> str:
        """格式化单个任务行，以真实 id 开头，子任务用缩进表示。"""
        status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        icon = status_icon.get(task["status"], "[?]")
        prefix = "  " if indent else ""
        return f"{prefix}#{task['id']} {icon} {task['text']}"

    def _summary(self) -> str:
        """生成状态统计摘要。"""
        counts: dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0}
        for t in self._tasks.values():
            s = t["status"]
            counts[s] = counts.get(s, 0) + 1
        parts = []
        if counts["pending"]:
            parts.append(f"{counts['pending']} 待办")
        if counts["in_progress"]:
            parts.append(f"{counts['in_progress']} 进行中")
        if counts["completed"]:
            parts.append(f"{counts['completed']} 已完成")
        return f"({', '.join(parts)})"

    def has_in_progress(self) -> bool:
        """是否有 in_progress 的任务。"""
        return any(t["status"] == "in_progress" for t in self._tasks.values())

    def current(self) -> str:
        """返回格式化的当前任务列表（供外部读取）。"""
        return self.format()


# ---- 模块级单例 + SCHEMA + run ----

_manager = TaskManager(STORAGE_PATH)

SCHEMA_CREATE = {
    "type": "function",
    "function": {
        "name": "task_create",
        "description": (
            "创建任务。支持批量创建和父子层级（通过 parent_id 指定父任务）。"
            "parent_id 只能指向已存在的根任务，不支持嵌套子任务。"
            "parent_id 是 task_list 输出中 '#' 后面的真实数字 id（不是 1.1 这种显示层级）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "任务描述（必填）",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "初始状态，默认 pending",
                            },
                            "parent_id": {
                                "type": "string",
                                "description": "父任务 id（可选）。是 task_list 输出中 '#' 后的数字，须指向根任务",
                            },
                        },
                        "required": ["text"],
                    },
                    "description": "要创建的任务列表",
                }
            },
            "required": ["tasks"],
        },
    },
}

SCHEMA_UPDATE = {
    "type": "function",
    "function": {
        "name": "task_update",
        "description": (
            "更新已有任务的状态或描述。支持批量更新。"
            "全局只能有一个 'in_progress' 任务。"
            "id 用 task_list 输出中 '#' 后面的真实数字（例如 '#6' 就传 '6'），不要用 1.1 这种显示层级序号。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "updates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "任务 id（必填）。task_list 输出中 '#' 后面的真实数字，不是 1.1 显示序号",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "新状态",
                            },
                            "text": {
                                "type": "string",
                                "description": "新描述（可选）",
                            },
                        },
                        "required": ["id"],
                    },
                    "description": "要更新的任务列表",
                }
            },
            "required": ["updates"],
        },
    },
}

SCHEMA_LIST = {
    "type": "function",
    "function": {
        "name": "task_list",
        "description": "查看当前任务列表，可选按状态筛选。",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "按状态筛选（可选，不传则显示全部）",
                }
            },
        },
    },
}


def create(tasks: list[dict]) -> str:
    """创建任务。"""
    return _manager.create(tasks)


def update(updates: list[dict]) -> str:
    """更新任务。"""
    return _manager.update(updates)


def list_tasks(status: str | None = None) -> str:
    """查看任务列表。"""
    return _manager.list_tasks(status)


def has_in_progress() -> bool:
    """是否有进行中的任务。"""
    return _manager.has_in_progress()


def current() -> str:
    """返回格式化的当前任务列表。"""
    return _manager.current()


def reset() -> None:
    """清空所有任务（仅用于测试/重置）。"""
    _manager._tasks = {}
    _manager._next_id = 1
    _manager._save()
