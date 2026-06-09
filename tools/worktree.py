"""worktree 工具 —— 各干各的目录，互不干扰。

为每个任务创建独立的 git worktree 目录，实现执行隔离：
  - worktree_create: 创建 worktree 并可选绑定任务
  - worktree_remove: 删除 worktree（可选完成任务）
  - worktree_keep: 保留 worktree（标记为 kept，不删除）
  - worktree_list: 列出所有 worktree 及其状态
  - worktree_exec: 在 worktree 目录中执行命令

核心机制：
  - WorktreeManager: 管理 worktree 注册表 + 生命周期事件
  - .worktrees/index.json: worktree 注册表
  - .worktrees/events.jsonl: 生命周期事件日志

与 core/loop.py 零耦合：所有隔离通过工厂函数创建 worktree-aware 的 handler 实现。
"""
from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from tools import bash as _bash
from tools import read_file as _read_file
from tools import write_file as _write_file

_MAX_OUTPUT_LENGTH = 50_000


def _truncate(text: str) -> str:
    return text[:_MAX_OUTPUT_LENGTH]


class WorktreeManager:
    """管理 git worktree 的创建、删除、注册表和事件日志。"""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._wt_dir = self._base_dir / ".worktrees"
        self._index_path = self._wt_dir / "index.json"
        self._events_path = self._wt_dir / "events.jsonl"
        self._lock = threading.Lock()

    # ---- 注册表持久化 ----

    def _load_index(self) -> list[dict]:
        """读取 worktree 注册表。"""
        if not self._index_path.exists():
            return []
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_index(self, entries: list[dict]) -> None:
        """原子写入注册表。"""
        self._wt_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._index_path)

    def _find_entry(self, entries: list[dict], name: str) -> dict | None:
        """在注册表中查找 worktree 条目。"""
        for e in entries:
            if e["name"] == name:
                return e
        return None

    # ---- 事件日志 ----

    def _emit_event(self, event: str, data: dict) -> None:
        """追加生命周期事件到 events.jsonl。"""
        self._wt_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            with open(self._events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---- 核心操作 ----

    def create(self, name: str, task_id: str | None = None) -> str:
        """创建 git worktree 并可选绑定任务。

        1. git worktree add -b wt/{name} .worktrees/{name} HEAD
        2. 更新 .worktrees/index.json
        3. 如果有 task_id：绑定任务
        4. 记录事件
        """
        # 名字校验
        if not name or not name.strip():
            return "错误：worktree 名字不能为空"
        name = name.strip()
        if not all(c.isalnum() or c in "_-" for c in name):
            return f"错误：worktree 名字 '{name}' 只能包含字母、数字、下划线和连字符"

        with self._lock:
            entries = self._load_index()

            # 检查重名
            if self._find_entry(entries, name):
                return f"错误：worktree '{name}' 已存在"

            # 检查 active worktree 是否已被占用
            for e in entries:
                if e.get("status") == "active" and e.get("task_id") == task_id and task_id:
                    return f"错误：任务 #{task_id} 已绑定 worktree '{e['name']}'"

            # 执行 git worktree add
            worktree_path = self._wt_dir / name
            branch_name = f"wt/{name}"
            try:
                result = subprocess.run(
                    ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"],
                    cwd=str(self._base_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    return f"错误：git worktree add 失败：{result.stderr.strip()}"
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                return f"错误：{e}"

            # 更新注册表
            now = datetime.now(timezone.utc).isoformat()
            entry = {
                "name": name,
                "branch": branch_name,
                "task_id": task_id,
                "status": "active",
                "created_at": now,
            }
            entries.append(entry)
            self._save_index(entries)

        # 绑定任务（如果指定了 task_id）
        if task_id:
            from tools import task as _task
            bind_result = _task._manager.bind_worktree(task_id, name)
            if bind_result.startswith("错误"):
                # 回滚：删除刚创建的 worktree
                self.remove(name, force=True)
                return bind_result

        # 记录事件
        self._emit_event("created", {"name": name, "branch": branch_name, "task_id": task_id})

        task_info = f"，已绑定任务 #{task_id}" if task_id else ""
        return f"worktree '{name}' 已创建（分支 {branch_name}）{task_info}"

    def remove(self, name: str, force: bool = False, complete_task: bool = False) -> str:
        """删除 worktree。

        1. git worktree remove .worktrees/{name} [--force]
        2. 如果 complete_task 且绑定了任务：完成任务
        3. 更新 index.json
        4. 记录事件
        """
        with self._lock:
            entries = self._load_index()
            entry = self._find_entry(entries, name)
            if not entry:
                return f"错误：worktree '{name}' 不存在"
            if entry["status"] == "removed":
                return f"错误：worktree '{name}' 已被删除"

            task_id = entry.get("task_id")
            old_status = entry["status"]

            # 执行 git worktree remove
            worktree_path = self._wt_dir / name
            try:
                cmd = ["git", "worktree", "remove", str(worktree_path)]
                if force:
                    cmd.append("--force")
                result = subprocess.run(
                    cmd,
                    cwd=str(self._base_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    if not force:
                        return f"错误：git worktree remove 失败（试试 force=true）：{result.stderr.strip()}"
                    # force 也失败，可能是路径不存在，继续清理注册表
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                return f"错误：{e}"

            # 清理分支（可选）
            try:
                subprocess.run(
                    ["git", "branch", "-d", entry["branch"]],
                    cwd=str(self._base_dir),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            # 更新注册表
            entry["status"] = "removed"
            entry["removed_at"] = datetime.now(timezone.utc).isoformat()
            self._save_index(entries)

        # 完成任务（如果指定）
        if complete_task and task_id:
            from tools import task as _task
            # 查找任务的 owner
            t = _task._manager._tasks.get(str(task_id))
            if t:
                owner = t.get("owner")
                if owner:
                    _task._manager.complete(task_id, owner)
                else:
                    # 无主任务直接标记完成
                    with _task._manager._lock:
                        tid = str(task_id)
                        task_obj = _task._manager._tasks.get(tid)
                        if task_obj:
                            task_obj["status"] = "completed"
                            task_obj["updated_at"] = datetime.now(timezone.utc).isoformat()
                            _task._manager._save()

            # 解除绑定
            from tools import task as _task
            _task._manager.unbind_worktree(task_id)

        # 记录事件
        self._emit_event("removed", {"name": name, "previous_status": old_status, "complete_task": complete_task})

        return f"worktree '{name}' 已删除"

    def keep(self, name: str) -> str:
        """保留 worktree（标记为 kept，不删除）。"""
        with self._lock:
            entries = self._load_index()
            entry = self._find_entry(entries, name)
            if not entry:
                return f"错误：worktree '{name}' 不存在"
            if entry["status"] != "active":
                return f"错误：worktree '{name}' 状态为 {entry['status']}，无法保留"

            entry["status"] = "kept"
            self._save_index(entries)

        self._emit_event("kept", {"name": name})
        return f"worktree '{name}' 已标记为 kept（不会被自动清理）"

    def list_worktrees(self) -> str:
        """列出所有 worktree 及其状态。"""
        entries = self._load_index()
        if not entries:
            return "（无 worktree）"

        lines = []
        for e in entries:
            task_info = f" → 任务 #{e['task_id']}" if e.get("task_id") else ""
            lines.append(f"  {e['name']} [{e['status']}] (分支: {e['branch']}){task_info}")
        return "\n".join(lines)

    def exec_command(self, name: str, command: str) -> str:
        """在 worktree 目录中执行命令。"""
        path = self.get_path(name)
        if path is None:
            return f"错误：worktree '{name}' 不存在或已删除"

        # 危险命令检查（复用 bash 工具的安全策略）
        if _bash._is_dangerous(command):
            return "错误：危险命令已被安全策略拦截。"

        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = (r.stdout + r.stderr).strip()
            return _truncate(out) if out else "（无输出）"
        except subprocess.TimeoutExpired:
            return "错误：命令执行超时（120 秒）。"
        except (FileNotFoundError, OSError) as e:
            return f"错误：{e}"

    def get_path(self, name: str) -> Path | None:
        """返回 worktree 的路径，不存在或已删除返回 None。"""
        entries = self._load_index()
        entry = self._find_entry(entries, name)
        if not entry or entry["status"] == "removed":
            return None
        path = self._wt_dir / name
        if not path.exists():
            return None
        return path

    def get_task_worktree(self, task_id: str) -> str | None:
        """返回任务绑定的 worktree 名称，没有则返回 None。"""
        entries = self._load_index()
        for e in entries:
            if e.get("task_id") == str(task_id) and e["status"] == "active":
                return e["name"]
        return None


# ---- 工厂函数：创建 worktree-aware 的 handler ----

def make_worktree_bash_handler(worktree_path: Path):
    """创建在 worktree 目录执行的 bash handler。"""
    def handler(command: str) -> str:
        if _bash._is_dangerous(command):
            return "错误：危险命令已被安全策略拦截。"
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = (r.stdout + r.stderr).strip()
            return _truncate(out) if out else "（无输出）"
        except subprocess.TimeoutExpired:
            return "错误：命令执行超时（120 秒）。"
        except (FileNotFoundError, OSError) as e:
            return f"错误：{e}"
    return handler


def _resolve_worktree_path(file_path: str, root: Path) -> Path:
    """将路径解析为绝对路径，相对路径以 worktree root 为基准。

    关键：Path("foo.txt").resolve() 会以 CWD 为基准，而 worktree handler
    需要以 worktree 目录为基准。所以相对路径要先 join worktree root 再 resolve。
    """
    p = Path(file_path).expanduser()
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def make_worktree_read_handler(worktree_path: Path):
    """创建在 worktree 目录读取文件的 read_file handler。"""
    root = worktree_path.resolve()

    def handler(file_path: str) -> str:
        target = _resolve_worktree_path(file_path, root)
        if not target.is_relative_to(root):
            return f"错误：路径穿越已拦截：'{file_path}' 解析到了 worktree 目录之外。"

        if not target.exists():
            return f"错误：文件不存在：{file_path}"
        if not target.is_file():
            return f"错误：不是文件：{file_path}"

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"错误：无法作为文本读取：{file_path}"
        except OSError as e:
            return f"错误：{e}"

        if len(content) > 50_000:
            content = content[:50_000] + "\n...（已截断）"
        return content
    return handler


def make_worktree_write_handler(worktree_path: Path):
    """创建在 worktree 目录写入文件的 write_file handler。"""
    root = worktree_path.resolve()

    def handler(file_path: str, content: str) -> str:
        target = _resolve_worktree_path(file_path, root)
        if not target.is_relative_to(root):
            return f"错误：路径穿越已拦截：'{file_path}' 解析到了 worktree 目录之外。"

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            return f"错误：文件写入失败：{e}"

        return f"成功：已将 {len(content)} 个字符写入 {file_path}"
    return handler


# ---- 模块级单例 + SCHEMA + run ----

_manager: WorktreeManager | None = None


def init(base_dir: Path | str | None = None) -> WorktreeManager:
    """初始化 WorktreeManager 单例。"""
    global _manager
    if base_dir is None:
        base_dir = Path.cwd()
    elif isinstance(base_dir, str):
        base_dir = Path(base_dir)
    _manager = WorktreeManager(base_dir)
    return _manager


def get_manager() -> WorktreeManager:
    """获取 WorktreeManager 单例。"""
    if _manager is None:
        return init()
    return _manager


SCHEMA_CREATE = {
    "type": "function",
    "function": {
        "name": "worktree_create",
        "description": (
            "创建一个 git worktree 目录，可选绑定到一个任务。"
            "worktree 是独立的 git 工作目录，绑定不同的分支，用于隔离不同任务的文件改动。"
            "创建后任务列表中会显示 [wt:name] 标记。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "worktree 名称（英文，如 auth-refactor、ui-login），将作为分支名和目录名",
                },
                "task_id": {
                    "type": "string",
                    "description": "要绑定的任务 id（可选）。绑定后队友认领该任务时会自动在 worktree 目录工作",
                },
            },
            "required": ["name"],
        },
    },
}

SCHEMA_REMOVE = {
    "type": "function",
    "function": {
        "name": "worktree_remove",
        "description": (
            "删除一个 worktree。如果绑定了任务，可以同时完成该任务。"
            "删除后 worktree 目录和分支都会被清理。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要删除的 worktree 名称",
                },
                "force": {
                    "type": "boolean",
                    "description": "是否强制删除（有未提交改动时需要设为 true）",
                },
                "complete_task": {
                    "type": "boolean",
                    "description": "是否同时完成绑定的任务（默认 false）",
                },
            },
            "required": ["name"],
        },
    },
}

SCHEMA_KEEP = {
    "type": "function",
    "function": {
        "name": "worktree_keep",
        "description": "保留 worktree（标记为 kept），不会被自动清理。适合想保留改动的场景。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要保留的 worktree 名称",
                },
            },
            "required": ["name"],
        },
    },
}

SCHEMA_LIST = {
    "type": "function",
    "function": {
        "name": "worktree_list",
        "description": "列出所有 worktree 及其状态（active/kept/removed）和绑定的任务。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

SCHEMA_EXEC = {
    "type": "function",
    "function": {
        "name": "worktree_exec",
        "description": "在指定 worktree 目录中执行命令（cwd 设为 worktree 路径）。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "worktree 名称",
                },
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                },
            },
            "required": ["name", "command"],
        },
    },
}


def create_worktree(name: str, task_id: str | None = None) -> str:
    """创建 worktree。"""
    return get_manager().create(name, task_id)


def remove_worktree(name: str, force: bool = False, complete_task: bool = False) -> str:
    """删除 worktree。"""
    return get_manager().remove(name, force, complete_task)


def keep_worktree(name: str) -> str:
    """保留 worktree。"""
    return get_manager().keep(name)


def list_worktrees() -> str:
    """列出所有 worktree。"""
    return get_manager().list_worktrees()


def exec_in_worktree(name: str, command: str) -> str:
    """在 worktree 中执行命令。"""
    return get_manager().exec_command(name, command)
