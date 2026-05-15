"""subagent 工具 —— 大任务拆小，每个小任务干净的上下文。

让主 agent 能把子任务委托给一个独立的子 agent 执行。
子 agent 拥有全新的消息上下文和独立的工具集，不会污染主 agent 的上下文。
执行完毕后把结果返回给主 agent。

核心思路：
  主 agent 调用 delegate(task) → 本工具启动一个新的 agent_loop →
  子 agent 用自己的上下文和工具执行 → 返回文字结果给主 agent

子 agent 的工具集包含 bash / read_file / write_file / load_skill，不含 delegate 本身，
防止无限递归（子 agent 再生孙子 agent）。
"""
from __future__ import annotations

# 子 agent 需要启动自己的循环，所以导入 core.loop
from core.loop import agent_loop

# 子 agent 可用的基础工具（不含 delegate，防止递归）
from tools import bash, read_file, write_file, skill

# ---- 子 agent 配置 ----

# 子 agent 的系统提示词：简短、聚焦，不加 todo/delegate 等高层机制
_SUB_SYSTEM = (
    "你是一个子 agent，负责独立完成被委托的特定任务。\n"
    "使用可用工具（bash、read_file、write_file、load_skill）高效完成任务，\n"
    "遇到不熟悉的领域时先调用 load_skill 加载相关技能。\n"
    "完成后用简洁的文字总结结果。不要过度解释，直接行动。"
)

# 子 agent 的工具列表（比主 agent 少，聚焦执行而非规划）
_SUB_TOOLS = [bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA, skill.SCHEMA]

# 子 agent 的工具处理函数映射
_SUB_HANDLERS = {
    "bash": bash.run,
    "read_file": read_file.run,
    "write_file": write_file.run,
    "load_skill": skill.run,
}

# 子 agent 最大循环轮次（比主 agent 少，防止子任务失控）
_MAX_SUB_TURNS = 20

# ---- 可视化回调 ----
# 由 agent 入口通过 set_subagent_callback() 设置
# 签名：fn(name: str, args: dict, output: str) -> None
_on_sub_tool_call = None


def set_subagent_callback(fn):
    """设置子 agent 工具调用的可视化回调。

    因为 run() 的签名是 run(task) -> str（被 handler dispatch 调用），
    无法直接传入回调参数，所以用模块级变量间接传递。

    参数：
        fn: 回调函数，签名为 fn(name, args, output)
    """
    global _on_sub_tool_call
    _on_sub_tool_call = fn


# ---- SCHEMA ----

SCHEMA = {
    "type": "function",
    "function": {
        "name": "delegate",
        # "将子任务委托给独立的子 agent 执行。子 agent 拥有全新的上下文和独立工具集。"
        "description": (
            "将子任务委托给独立的子 agent 执行。"
            "子 agent 拥有全新的上下文和工具集（bash、read_file、write_file、load_skill），"
            "执行完毕后返回结果摘要。适用于需要独立隔离执行的多步操作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    # "Description of the task to delegate"
                    "description": "要委托给子 agent 执行的具体任务描述",
                },
            },
            "required": ["task"],
        },
    },
}


# ---- run ----


def run(task: str) -> str:
    """启动子 agent 执行任务，返回结果摘要。

    子 agent 获得全新的消息历史（干净上下文）和独立的工具集，
    在自己的 agent_loop 中执行，完成后返回文字结果。

    参数：
        task: 子任务描述

    返回：
        子 agent 的执行结果（文字摘要）
    """
    # 为子 agent 创建全新的消息历史（只有一条 user 消息）
    # 这是"干净上下文"的关键：子 agent 看不到主 agent 的对话历史
    messages = [{"role": "user", "content": task}]

    # 启动子 agent 的独立循环
    stop_reason = agent_loop(
        messages,
        system=_SUB_SYSTEM,
        tools=_SUB_TOOLS,
        handlers=_SUB_HANDLERS,
        max_turns=_MAX_SUB_TURNS,
        on_tool_call=_on_sub_tool_call,  # 可选的可视化回调
    )

    # 从子 agent 的对话历史中倒序查找最后的文本输出
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            text = msg["content"].strip()
            if text:
                return text

    # 如果子 agent 没有文本输出（全是工具调用，没有最终文字回复）
    return f"（子 agent 已完成，stop_reason={stop_reason}，但未返回文字摘要）"
