"""team 工具 —— 任务太大一个人干不完，要能分给队友。

把 s04 的一次性 delegate 升级为持久化的队友：
  - 有名有姓（name + role）
  - 能并发干活（独立线程）
  - 能互相发消息（JSONL inbox）
  - working / idle 循环：干完活不退出，poll inbox 等新任务

核心机制：
  - TeammateManager: 管理花名册 + 消息总线 + 队友线程
  - spawn(name, role, prompt): 创建队友，启动 _teammate_loop 线程
  - send(to, content) / broadcast(content): 追加消息到 JSONL inbox
  - read_inbox(name): 读取并清空 inbox（drain-on-read）
  - status(): 格式化花名册
  - shutdown_all(): 通知所有队友停止
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from core.loop import agent_loop
from tools import bash, read_file, write_file, skill

# ---- 常量 ----

_MAX_OUTPUT_LENGTH = 50_000
_RESERVED_NAMES = {"lead", "system", "all"}
_POLL_INTERVAL = 1.0  # 队友 idle 时 poll inbox 的间隔（秒）


def format_inbox_messages(messages: list[dict]) -> str:
    """格式化 inbox 消息列表，处理结构化协议消息。

    普通消息保持原样（向后兼容），协议消息按类型格式化为可读提示。
    """
    parts = []
    for msg in messages:
        msg_type = msg.get("type")
        if msg_type == "shutdown_request":
            metadata = msg.get("metadata", {})
            req_id = metadata.get("request_id", "?")
            parts.append(
                f"[协议请求] 收到 shutdown_request (req_id: #{req_id}，来自 {msg['from']})\n"
                f"请使用 shutdown_response 工具响应此请求"
                f"（approve=true 收尾退出，approve=false 拒绝并继续工作）。"
            )
        elif msg_type == "shutdown_response":
            metadata = msg.get("metadata", {})
            req_id = metadata.get("request_id", "?")
            approved = metadata.get("approve", False)
            status = "已批准" if approved else "已拒绝"
            content = msg.get("content", "")
            parts.append(
                f"[关机响应] 来自 {msg['from']}，req_id: #{req_id}，{status}"
                + (f"\n原因：{content}" if content else "")
            )
        elif msg_type == "plan_request":
            metadata = msg.get("metadata", {})
            req_id = metadata.get("request_id", "?")
            content = msg.get("content", "")
            parts.append(
                f"[计划请求] 来自 {msg['from']}，req_id: #{req_id}\n{content}"
            )
        elif msg_type == "plan_approval_response":
            metadata = msg.get("metadata", {})
            req_id = metadata.get("request_id", "?")
            approved = metadata.get("approve", False)
            status = "已批准" if approved else "已拒绝"
            content = msg.get("content", "")
            parts.append(
                f"[计划审批结果] req_id: #{req_id}，{status}"
                + (f"\n{content}" if content else "")
                + ("\n你可以开始执行计划。" if approved else "\n请调整计划后重新提交。")
            )
        else:
            parts.append(f"来自 {msg['from']}：{msg['content']}")
    return "\n".join(parts)


def format_inbox(inbox_json: str) -> str:
    """将 read_inbox 返回的 JSON 格式化为可读文本，处理结构化协议消息。"""
    if inbox_json == "[]":
        return ""
    messages = json.loads(inbox_json)
    return format_inbox_messages(messages)


def _truncate(text: str) -> str:
    """截断超长输出。"""
    return text[:_MAX_OUTPUT_LENGTH]


class TeammateManager:
    """管理队友花名册、消息队列和线程。"""

    def __init__(self, team_dir: Path) -> None:
        self.dir = team_dir
        self.config_path = self.dir / "config.json"
        self.inbox_dir = self.dir / "inbox"
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._graceful_shutdown: set[str] = set()

        # 队友扩展配置（由 agent 脚本设置，_teammate_loop 使用）
        self._teammate_extra_tools: list = []
        self._teammate_handler_factories: dict[str, callable] = {}
        self._teammate_system_suffix: str = ""

        # 确保目录存在
        self.dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        # 初始化空花名册
        if not self.config_path.exists():
            self._save_config({"lead": {"role": "lead", "status": "idle"}, "teammates": {}})

    # ---- 花名册 ----

    def _load_config(self) -> dict:
        """读取花名册配置。"""
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _save_config(self, config: dict) -> None:
        """写入花名册配置。"""
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- 消息总线 ----

    def _inbox_path(self, name: str) -> Path:
        """返回 name 的 inbox 文件路径。"""
        safe_name = name.replace("/", "_").replace("\\", "_")
        return self.inbox_dir / f"{safe_name}.jsonl"

    def _validate_recipient(self, to: str) -> str | None:
        """校验接收者是否存在。返回错误信息或 None。"""
        if to == "lead":
            return None  # lead 始终存在
        config = self._load_config()
        if to not in config["teammates"]:
            return f"接收者 '{to}' 不存在于团队中"
        return None

    def _validate_teammate_alive(self, name: str) -> str | None:
        """校验队友是否还活着（能接收消息）。返回错误信息或 None。"""
        config = self._load_config()
        info = config["teammates"].get(name)
        if not info:
            return f"队友 '{name}' 不存在"
        if info.get("status") == "stopped":
            return f"队友 '{name}' 已停止，无法接收消息"
        thread = self._threads.get(name)
        if thread is None:
            return f"队友 '{name}' 无活跃线程，无法接收消息"
        if not thread.is_alive():
            return f"队友 '{name}' 已退出，无法接收消息"
        return None

    def send(self, sender: str, to: str, content: str,
             msg_type: str | None = None, metadata: dict | None = None) -> str:
        """追加消息到 to 的 inbox。支持结构化协议消息（msg_type + metadata）。"""
        # 校验接收者存在
        err = self._validate_recipient(to)
        if err:
            return f"发送失败：{err}"
        # 校验接收者活着（lead 除外）
        if to != "lead":
            err = self._validate_teammate_alive(to)
            if err:
                return f"发送失败：{err}"

        msg = {"from": sender, "content": content}
        if msg_type:
            msg["type"] = msg_type
        if metadata:
            msg["metadata"] = metadata

        path = self._inbox_path(to)
        with self._lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        return f"消息已发送给 {to}"

    def broadcast(self, sender: str, content: str) -> str:
        """给所有队友发消息。"""
        config = self._load_config()
        recipients = ["lead"] + list(config["teammates"].keys())
        recipients = [r for r in recipients if r != sender]
        for name in recipients:
            self.send(sender, name, content)
        return f"消息已广播给 {len(recipients)} 人：{', '.join(recipients)}"

    def read_inbox(self, name: str) -> str:
        """读取并清空 name 的 inbox（drain-on-read）。

        先逐行 parse JSONL，再对每条消息的 content 截断，
        最后格式化为 JSON 返回。避免在 JSON 字符串中间截断导致 parse 失败。
        """
        path = self._inbox_path(name)
        if not path.exists():
            return "[]"

        with self._lock:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                return "[]"
            # 清空
            path.write_text("", encoding="utf-8")

        messages = []
        for line in content.split("\n"):
            line = line.strip()
            if line:
                try:
                    msg = json.loads(line)
                    # 对每条消息的 content 做截断，保护 JSON 结构
                    if isinstance(msg.get("content"), str) and len(msg["content"]) > _MAX_OUTPUT_LENGTH:
                        msg["content"] = msg["content"][:_MAX_OUTPUT_LENGTH]
                    messages.append(msg)
                except json.JSONDecodeError:
                    pass

        result = json.dumps(messages, ensure_ascii=False, indent=2)
        return result

    # ---- 队友管理 ----

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """创建队友，启动 _teammate_loop 线程。"""
        # 名字校验
        if not name or not name.strip():
            return "错误：队友名字不能为空"
        name = name.strip()
        if name.lower() in _RESERVED_NAMES:
            return f"错误：'{name}' 是保留名，不能用作队友名"
        if not all(c.isalnum() or c in "_-" for c in name):
            return f"错误：队友名字 '{name}' 只能包含字母、数字、下划线和连字符"

        config = self._load_config()

        if name in config["teammates"]:
            return f"队友 {name} 已存在"

        # 更新花名册
        config["teammates"][name] = {"role": role, "status": "working"}
        self._save_config(config)

        # 启动线程
        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
            name=f"teammate-{name}",
        )
        self._threads[name] = thread
        thread.start()

        return f"队友 {name}（{role}）已创建并开始工作"

    def update_status(self, name: str, status: str) -> None:
        """更新队友状态。"""
        config = self._load_config()
        if name in config["teammates"]:
            config["teammates"][name]["status"] = status
            self._save_config(config)

    def status(self) -> str:
        """格式化花名册。"""
        config = self._load_config()
        lines = ["=== 团队状态 ==="]
        lines.append(f"  lead（调度者）- idle")
        for name, info in config["teammates"].items():
            lines.append(f"  {name}（{info['role']}）- {info['status']}")
        return "\n".join(lines)

    def configure_teammate(self, extra_tools=None, handler_factories=None, system_suffix=""):
        """配置队友的额外工具和系统提示词后缀（s10+ 使用）。

        参数：
            extra_tools: 追加到队友工具列表的 SCHEMA 列表
            handler_factories: {tool_name: factory} 工厂函数，factory(teammate_name) → handler
            system_suffix: 追加到队友 system prompt 的文本
        """
        if extra_tools is not None:
            self._teammate_extra_tools = extra_tools
        if handler_factories is not None:
            self._teammate_handler_factories = handler_factories
        if system_suffix:
            self._teammate_system_suffix = system_suffix

    def request_graceful_exit(self, name: str) -> None:
        """标记队友需要优雅退出（由 ProtocolTracker 调用）。"""
        self._graceful_shutdown.add(name)

    def _should_exit(self, name: str) -> bool:
        """检查队友是否需要优雅退出。"""
        return name in self._graceful_shutdown

    def shutdown_all(self) -> None:
        """给所有队友发 shutdown 消息。"""
        config = self._load_config()
        for name in config["teammates"]:
            msg = {"from": "system", "content": "__shutdown__"}
            path = self._inbox_path(name)
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def has_working_teammates(self) -> bool:
        """是否有正在工作的队友（线程活着 + 状态 working）。"""
        config = self._load_config()
        for name, info in config["teammates"].items():
            if info["status"] == "working" and self.is_teammate_alive(name):
                return True
        return False

    def has_alive_teammates(self) -> bool:
        """是否有活着的队友线程。"""
        return any(t.is_alive() for t in self._threads.values())

    def is_teammate_alive(self, name: str) -> bool:
        """检查队友线程是否还活着。"""
        thread = self._threads.get(name)
        return thread is not None and thread.is_alive()

    # ---- 队友循环 ----

    def _teammate_loop(self, name: str, role: str, prompt: str) -> None:
        """队友的持久化循环：working → idle → poll inbox → working → ...

        不退出（除非收到 __shutdown__ 或优雅关机批准）。
        idle 时每秒 poll inbox，有新消息就重新进入 working 状态跑 agent_loop。
        """
        teammate_system = (
            f"你是队友 {name}，角色是 {role}。\n"
            "使用可用工具（bash、read_file、write_file、load_skill、send）完成任务。\n"
            "收到其他队友的消息时，根据内容采取行动。\n"
            "完成后通过 send 向 lead 汇报结果，用简短的文字总结你做了什么。\n"
            "不要重复已完成的操作。"
        ) + self._teammate_system_suffix

        # 队友工具集：bash + 文件 + 技能 + send（绑定 sender）
        def _send_for_teammate(to: str, content: str) -> str:
            return self.send(name, to, content)

        teammate_tools = [
            bash.SCHEMA,
            read_file.SCHEMA,
            write_file.SCHEMA,
            skill.SCHEMA,
            SCHEMA_SEND,
        ] + self._teammate_extra_tools

        teammate_handlers = {
            "bash": bash.run,
            "read_file": read_file.run,
            "write_file": write_file.run,
            "load_skill": skill.run,
            "send": _send_for_teammate,
        }
        # 添加扩展工具 handler（工厂函数绑定队友名）
        for tool_name, factory in self._teammate_handler_factories.items():
            teammate_handlers[tool_name] = factory(name)

        # ---- 第一轮：用初始 prompt 启动 ----
        messages: list[dict] = [{"role": "user", "content": prompt}]
        print(f"\033[36m  [{name}] 开始工作...\033[0m")

        if self._run_one_task(name, messages, teammate_system, teammate_tools, teammate_handlers):
            return  # 收到 shutdown

        # ---- 之后进入 idle → poll 循环 ----
        while True:
            # idle
            self.update_status(name, "idle")
            print(f"\033[36m  [{name}] idle，等待新消息...\033[0m")

            # poll inbox，等新消息或 shutdown
            while True:
                inbox = self.read_inbox(name)
                inbox_data = json.loads(inbox)
                if not inbox_data:
                    time.sleep(_POLL_INTERVAL)
                    continue

                # 检查 shutdown（向后兼容）
                for msg in inbox_data:
                    if msg.get("content") == "__shutdown__":
                        print(f"\033[36m  [{name}] 收到 shutdown，退出\033[0m")
                        self.update_status(name, "stopped")
                        return

                # 有新任务，跳出 poll 循环
                break

            # 收到新消息，进入 working
            self.update_status(name, "working")
            inbox_text = format_inbox_messages(inbox_data)
            # 新任务用干净的上下文
            messages = [{"role": "user", "content": f"[收到消息]\n{inbox_text}"}]
            print(f"\033[36m  [{name}] 收到新任务，开始工作...\033[0m")

            if self._run_one_task(name, messages, teammate_system, teammate_tools, teammate_handlers):
                return  # 收到 shutdown

            # 检查优雅关机
            if self._should_exit(name):
                self.update_status(name, "stopped")
                print(f"\033[36m  [{name}] 优雅关机完成\033[0m")
                return

    def _run_one_task(self, name: str, messages: list, system: str, tools: list, handlers: dict) -> bool:
        """执行一个任务（跑 agent_loop 直到模型停止调工具），然后汇报。

        返回 True 表示收到 __shutdown__，调用方应退出线程。
        """
        for _ in range(20):
            # drain inbox（工作期间也可能收到消息）
            inbox = self.read_inbox(name)
            inbox_data = json.loads(inbox)
            if inbox_data:
                # 检查 shutdown（向后兼容）
                for msg in inbox_data:
                    if msg.get("content") == "__shutdown__":
                        print(f"\033[36m  [{name}] 收到 shutdown，退出\033[0m")
                        self.update_status(name, "stopped")
                        return True
                inbox_text = format_inbox_messages(inbox_data)
                messages.append({"role": "user", "content": f"[收到消息]\n{inbox_text}"})

            # 调用 agent_loop（一轮）
            stop_reason = agent_loop(
                messages,
                system=system,
                tools=tools,
                handlers=handlers,
                max_turns=20,
            )

            # 如果模型不再调工具，本轮任务完成
            if stop_reason != "tool_calls":
                break

            # 检查优雅关机（shutdown_response approve=true 后提前退出）
            if self._should_exit(name):
                break

        # 优雅关机时跳过汇报（respond_shutdown 已发过结构化消息）
        if self._should_exit(name):
            print(f"\033[36m  [{name}] 关机已批准，退出\033[0m")
            return False

        # 取最后的文本输出
        final_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                text = msg["content"].strip()
                if text:
                    final_text = text
                    break

        if final_text:
            self.send(name, "lead", final_text)
        else:
            self.send(name, "lead", f"队友 {name} 已完成工作")

        print(f"\033[36m  [{name}] 任务完成，已汇报 lead\033[0m")
        return False  # 正常完成，未收到 shutdown


# ---- SCHEMA 定义 ----

SCHEMA_SPAWN = {
    "type": "function",
    "function": {
        "name": "spawn",
        "description": (
            "创建一个队友并分配任务。队友会在后台独立工作，"
            "完成后通过消息通知你。队友完成后不会消失，可以继续发新任务。"
            "可以同时创建多个队友并发干活。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "队友的名字（英文，如 alice、bob），不能是 lead/system 等保留名",
                },
                "role": {
                    "type": "string",
                    "description": "队友的角色（如 coder、tester、researcher）",
                },
                "prompt": {
                    "type": "string",
                    "description": "给队友的任务描述，越具体越好",
                },
            },
            "required": ["name", "role", "prompt"],
        },
    },
}

SCHEMA_SEND = {
    "type": "function",
    "function": {
        "name": "send",
        "description": (
            "给指定队友发消息。消息会追加到队友的 inbox，"
            "空闲队友会自动读取并开始工作。也可以给 lead 发消息。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "接收者名字（必须是已创建的队友名或 lead）",
                },
                "content": {
                    "type": "string",
                    "description": "消息内容",
                },
            },
            "required": ["to", "content"],
        },
    },
}

SCHEMA_BROADCAST = {
    "type": "function",
    "function": {
        "name": "broadcast",
        "description": "给所有队友（除自己外）广播消息。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "广播内容",
                },
            },
            "required": ["content"],
        },
    },
}

SCHEMA_STATUS = {
    "type": "function",
    "function": {
        "name": "team_status",
        "description": "查看团队状态，包括所有队友的名字、角色和工作状态。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


# ---- 模块级单例 + 函数 ----

_manager: TeammateManager | None = None


def init(team_dir: Path | str | None = None) -> TeammateManager:
    """初始化 TeammateManager 单例。"""
    global _manager
    if team_dir is None:
        team_dir = Path.cwd() / ".team"
    elif isinstance(team_dir, str):
        team_dir = Path(team_dir)
    _manager = TeammateManager(team_dir)
    return _manager


def get_manager() -> TeammateManager:
    """获取 TeammateManager 单例。"""
    if _manager is None:
        return init()
    return _manager


def spawn(name: str, role: str, prompt: str) -> str:
    """创建队友。"""
    return get_manager().spawn(name, role, prompt)


def send(to: str, content: str) -> str:
    """Lead 给队友发消息。"""
    return get_manager().send("lead", to, content)


def broadcast(content: str) -> str:
    """Lead 广播消息。"""
    return get_manager().broadcast("lead", content)


def read_inbox(name: str = "lead") -> str:
    """读取并清空 inbox。"""
    return get_manager().read_inbox(name)


def team_status() -> str:
    """查看团队状态。"""
    return get_manager().status()


def shutdown_all() -> None:
    """通知所有队友停止。"""
    get_manager().shutdown_all()


def has_working_teammates() -> bool:
    """是否有正在工作的队友。"""
    return get_manager().has_working_teammates()


def has_alive_teammates() -> bool:
    """是否有活着的队友线程。"""
    return get_manager().has_alive_teammates()


def reset() -> None:
    """重置团队（清理 .team 目录）。"""
    global _manager
    if _manager is not None:
        _manager.shutdown_all()
        # 等线程退出（最多 3 秒）
        for t in _manager._threads.values():
            t.join(timeout=3)
    import shutil
    team_dir = Path.cwd() / ".team"
    if team_dir.exists():
        shutil.rmtree(team_dir)
    _manager = None
