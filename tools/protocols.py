"""protocols 工具 —— 团队协议管理器。

追踪两类协议请求（关机、计划审批），每个请求走 pending → approved/rejected 的 FSM。

两个协议：
  Shutdown Protocol: Lead 发 shutdown_request → Teammate 回 shutdown_response
  Plan Approval:     Teammate 发 plan_submit → Lead 回 plan_review

共享 FSM: [pending] --approve--> [approved]
          [pending] --reject---> [rejected]

核心约束：core/loop.py 一行不改。
"""
from __future__ import annotations

import threading
import uuid


class ProtocolTracker:
    """追踪两类协议请求，FSM: pending → approved/rejected。"""

    def __init__(self):
        self.shutdown_requests: dict[str, dict] = {}  # {req_id: {target, status}}
        self.plan_requests: dict[str, dict] = {}      # {req_id: {from, plan, status}}
        self.lock = threading.Lock()
        self._manager = None

    def _mgr(self):
        """Lazy init: 获取 TeammateManager 单例。"""
        if self._manager is None:
            from tools.team import get_manager
            self._manager = get_manager()
        return self._manager

    # ---- Shutdown Protocol ----

    def request_shutdown(self, name: str) -> str:
        """Lead 请求队友优雅关机。"""
        # lead 不能关机自己
        if name == "lead":
            return "关机请求失败：不能对 lead 发起关机请求"
        # 校验目标存在
        err = self._mgr()._validate_recipient(name)
        if err:
            return f"关机请求失败：{err}"
        # 校验目标还活着（已停止的队友无需关机）
        err = self._mgr()._validate_teammate_alive(name)
        if err:
            return f"关机请求失败：{err}"

        req_id = uuid.uuid4().hex[:8]
        with self.lock:
            self.shutdown_requests[req_id] = {"target": name, "status": "pending"}
        self._mgr().send(
            "lead", name,
            "Please shut down gracefully.",
            msg_type="shutdown_request",
            metadata={"request_id": req_id},
        )
        return f"关机请求 #{req_id} 已发送给 {name}（状态: pending）"

    def respond_shutdown(
        self, sender: str, req_id: str, approve: bool, reason: str = ""
    ) -> str:
        """Teammate 响应关机请求。"""
        with self.lock:
            req = self.shutdown_requests.get(req_id)
            if not req:
                return f"错误：未知的请求 ID #{req_id}"
            if req["status"] != "pending":
                return f"错误：请求 #{req_id} 已经是 {req['status']} 状态"
            if req["target"] != sender:
                return f"错误：请求 #{req_id} 的目标是 {req['target']}，不是 {sender}"
            req["status"] = "approved" if approve else "rejected"

        self._mgr().send(
            sender, "lead", reason or "",
            msg_type="shutdown_response",
            metadata={"request_id": req_id, "approve": approve},
        )

        if approve:
            self._mgr().request_graceful_exit(sender)
            return f"关机请求 #{req_id} 已批准。正在收尾退出..."
        return f"关机请求 #{req_id} 已拒绝，继续工作。"

    # ---- Plan Approval Protocol ----

    def submit_plan(self, sender: str, plan: str) -> str:
        """Teammate 提交计划请求审批。"""
        req_id = uuid.uuid4().hex[:8]
        with self.lock:
            self.plan_requests[req_id] = {
                "from": sender, "plan": plan, "status": "pending"
            }
        self._mgr().send(
            sender, "lead", plan,
            msg_type="plan_request",
            metadata={"request_id": req_id},
        )
        return f"计划已提交（req_id: #{req_id}），等待 lead 审批"

    def review_plan(
        self, req_id: str, approve: bool, feedback: str = ""
    ) -> str:
        """Lead 审批队友的计划。"""
        with self.lock:
            req = self.plan_requests.get(req_id)
            if not req:
                return f"错误：未知的计划请求 ID #{req_id}"
            if req["status"] != "pending":
                return f"错误：请求 #{req_id} 已经是 {req['status']} 状态"
            target = req["from"]
            original_plan = req["plan"]

            # 校验队友还活着，否则审批结果发不出去
            err = self._mgr()._validate_teammate_alive(target)
            if err:
                return f"计划审批失败：{err}（请求 #{req_id} 仍为 pending）"

            req["status"] = "approved" if approve else "rejected"

        # 批准时把原始计划拼进消息，让队友在干净上下文下也能知道要做什么
        if approve:
            content = f"你的计划已批准。\n\n原始计划：{original_plan}"
            if feedback:
                content += f"\n\n反馈：{feedback}"
        else:
            content = feedback or "计划被拒绝，请调整后重新提交。"

        self._mgr().send(
            "lead", target, content,
            msg_type="plan_approval_response",
            metadata={"request_id": req_id, "approve": approve},
        )

        status = "已批准" if approve else "已拒绝"
        return f"计划 #{req_id}（来自 {target}）{status}"

    # ---- 查看状态 ----

    def list_requests(self) -> str:
        """列出所有协议请求。"""
        with self.lock:
            lines = []
            for rid, r in self.shutdown_requests.items():
                lines.append(f"  关机 #{rid} → {r['target']} ({r['status']})")
            for rid, r in self.plan_requests.items():
                lines.append(f"  计划 #{rid} ← {r['from']} ({r['status']})")
        if not lines:
            return "无待处理请求"
        return "=== 协议请求 ===\n" + "\n".join(lines)


# ---- 模块级单例 ----

_tracker = ProtocolTracker()


# ---- SCHEMA 定义 ----

SCHEMA_SHUTDOWN_REQUEST = {
    "type": "function",
    "function": {
        "name": "shutdown_request",
        "description": (
            "请求队友优雅关机。会发送带唯一 req_id 的结构化请求给队友，"
            "队友通过 shutdown_response 响应。比直接发 __shutdown__ 更安全，"
            "队友有机会收尾工作后再退出。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要关机的队友名字",
                },
            },
            "required": ["name"],
        },
    },
}

SCHEMA_SHUTDOWN_RESPONSE = {
    "type": "function",
    "function": {
        "name": "shutdown_response",
        "description": (
            "响应关机请求。收到 shutdown_request 后使用。"
            "approve=true 表示同意关机，你会收尾工作并退出。"
            "approve=false 表示拒绝关机，继续工作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "关机请求的 ID",
                },
                "approve": {
                    "type": "boolean",
                    "description": "是否批准关机",
                },
                "reason": {
                    "type": "string",
                    "description": "批准/拒绝的原因（可选）",
                },
            },
            "required": ["request_id", "approve"],
        },
    },
}

SCHEMA_PLAN_SUBMIT = {
    "type": "function",
    "function": {
        "name": "plan_submit",
        "description": (
            "提交计划请求审批。遇到高风险操作时使用（如删除文件、重构核心代码）。"
            "提交后等待 lead 审批，审批通过后再执行。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "计划描述，包括要做什么、为什么、预期影响",
                },
            },
            "required": ["plan"],
        },
    },
}

SCHEMA_PLAN_REVIEW = {
    "type": "function",
    "function": {
        "name": "plan_review",
        "description": (
            "审批队友提交的计划。approve=true 允许执行，approve=false 拒绝。"
            "队友会收到审批结果，调整计划或放弃。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "计划请求的 ID",
                },
                "approve": {
                    "type": "boolean",
                    "description": "是否批准计划",
                },
                "feedback": {
                    "type": "string",
                    "description": "审批反馈（建议、修改意见等，可选）",
                },
            },
            "required": ["request_id", "approve"],
        },
    },
}

SCHEMA_LIST_REQUESTS = {
    "type": "function",
    "function": {
        "name": "list_requests",
        "description": "查看所有协议请求的状态（关机请求和计划审批请求）。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


# ---- 模块级函数（Lead agent 直接使用）----


def shutdown_request(name: str) -> str:
    """Lead 请求队友关机。"""
    return _tracker.request_shutdown(name)


def plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    """Lead 审批计划。"""
    return _tracker.review_plan(request_id, approve, feedback)


def list_requests() -> str:
    """列出所有协议请求。"""
    return _tracker.list_requests()


# ---- Teammate 用的工厂函数 ----


def make_shutdown_response_handler(teammate_name: str):
    """为队友创建 shutdown_response handler（绑定队友名）。"""
    def handler(request_id: str, approve: bool, reason: str = "") -> str:
        return _tracker.respond_shutdown(teammate_name, request_id, approve, reason)
    return handler


def make_plan_submit_handler(teammate_name: str):
    """为队友创建 plan_submit handler（绑定队友名）。"""
    def handler(plan: str) -> str:
        return _tracker.submit_plan(teammate_name, plan)
    return handler


def reset():
    """重置协议追踪器（测试/重置用）。"""
    global _tracker
    _tracker = ProtocolTracker()
