"""agent_loop —— s01 的地基循环函数，后面 11 课都不会改这个函数。

这个函数实现了 Agent 的核心机制：
  模型思考 → 调用工具 → harness 执行 → 结果回灌 → 模型继续思考
  直到模型不再需要调用工具为止。
"""
from __future__ import annotations  # 启用延迟类型注解求值

from typing import Any, Callable  # 类型提示工具：Any 表示任意类型，Callable 表示可调用对象

from .llm import MODEL, client  # 从同包的 llm.py 导入 LLM 客户端和模型名

# 定义工具处理函数的类型别名：接受任意参数，返回字符串
ToolHandler = Callable[..., str]


def agent_loop(
    messages: list[dict[str, Any]],  # 对话历史，会就地修改（往里追加消息）
    *,
    system: str,  # 系统提示词，告诉模型它的角色和行为规范
    tools: list[dict[str, Any]],  # 工具的 JSON Schema 定义列表，传给 API 告诉模型有哪些工具可用
    handlers: dict[str, ToolHandler],  # 工具名 → 处理函数的映射，实现"加工具只加 handler"
    max_turns: int = 50,  # 最大循环轮次，作为兜底保险丝防止死循环
    on_tool_call: Callable[[str, dict, str], None] | None = None,  # 可选的回调钩子，用于打印/日志
) -> str:  # 返回循环退出的原因（stop_reason）
    """就地驱动 messages[] 直到模型停止调工具；返回退出时的 stop_reason。

    参数说明：
    - messages: 对话历史列表，函数会直接向其中追加 assistant 和 user 消息
    - system: 系统提示词
    - tools: 传给 API 的工具 schema 列表
    - handlers: 工具名到处理函数的映射字典，s02 起"加一个工具只加一个 handler"
    - max_turns: 兜底保险丝，防止模型陷入工具调用死循环
    - on_tool_call(name, input, output): 可选观测钩子，便于 REPL 打印工具调用过程
    """
    # 主循环：最多跑 max_turns 轮，每轮是一次 API 调用
    for turn in range(1, max_turns + 1):
        # 调用 Anthropic Messages API，让模型根据当前对话历史生成回复
        response = client.messages.create(
            model=MODEL,  # 使用的模型（从环境变量读取，如 glm-5.1）
            system=system,  # 系统提示词
            messages=messages,  # 对话历史
            tools=tools,  # 可用工具列表
            max_tokens=8000,  # 单次回复的最大 token 数
        )

        # 把模型的回复追加到对话历史中（assistant 角色）
        messages.append({"role": "assistant", "content": response.content})

        # 如果模型的 stop_reason 不是 "tool_use"，说明它不需要再调工具了，直接退出循环
        # 可能的值："end_turn"（正常结束）、"max_tokens"（达到上限）等
        if response.stop_reason != "tool_use":
            return response.stop_reason  # 返回退出原因

        # --- 以下是处理工具调用的逻辑 ---

        # 收集本轮所有工具调用的结果
        results = []

        # 遍历模型回复中的每一个内容块（可能是文本块或工具调用块）
        for block in response.content:
            # 只处理 tool_use 类型的块，跳过文本块
            if getattr(block, "type", None) != "tool_use":
                continue

            # 从 handlers 字典中查找对应的处理函数
            handler = handlers.get(block.name)

            # 如果找到了处理函数就调用它，传入模型提供的参数；
            # 如果没找到，返回错误提示（不会崩溃，优雅降级）
            output = (
                handler(**block.input)
                if handler
                else f"Error: no handler registered for tool '{block.name}'"
            )

            # 如果提供了观测钩子回调，就调用它（用于在终端打印工具执行过程）
            if on_tool_call:
                on_tool_call(block.name, block.input, output)

            # 把工具执行结果包装成 API 要求的 tool_result 格式，
            # tool_use_id 必须和模型返回的 block.id 对应，否则 API 会报 400 错误
            results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": output}
            )

        # 把本轮所有工具结果作为一条 user 消息追加到对话历史
        # 注意：必须把同一轮的所有 tool_result 打包进同一个 user 消息中，
        # 否则 API 会因为 tool_use_id 不匹配而返回 400 错误
        messages.append({"role": "user", "content": results})

    # 如果循环跑满了 max_turns 轮还没退出，返回自定义的退出原因
    return "max_turns_exceeded"
