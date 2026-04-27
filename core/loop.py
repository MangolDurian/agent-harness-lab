"""agent_loop —— s01 的地基循环函数，后面 11 课都不会改这个函数。

这个函数实现了 Agent 的核心机制：
  模型思考 → 调用工具 → harness 执行 → 结果回灌 → 模型继续思考
  直到模型不再需要调用工具为止。

本版本使用 OpenAI 兼容 API 格式（适配智谱 AI / GLM 5.1），
与 Anthropic 格式的主要区别：
  - 工具调用通过 tool_calls 字段返回（而非 content 中的 tool_use 块）
  - 工具结果通过 role="tool" 的消息返回（而非 role="user" 中的 tool_result 块）
  - 系统提示词放在 messages 数组中（而非单独的 system 参数）
"""
from __future__ import annotations  # 启用延迟类型注解求值

import json  # JSON 解析库，用于解析工具调用参数（OpenAI 格式参数是 JSON 字符串）
from typing import Any, Callable  # 类型提示工具：Any 表示任意类型，Callable 表示可调用对象

from .llm import MODEL, client  # 从同包的 llm.py 导入 LLM 客户端和模型名

# 定义工具处理函数的类型别名：接受任意关键字参数，返回字符串
ToolHandler = Callable[..., str]


def agent_loop(
    messages: list[dict[str, Any]],  # 对话历史，会就地修改（往里追加消息）
    *,
    system: str,  # 系统提示词，告诉模型它的角色和行为规范
    tools: list[dict[str, Any]],  # 工具的 JSON Schema 定义列表（OpenAI function calling 格式）
    handlers: dict[str, ToolHandler],  # 工具名 → 处理函数的映射，实现"加工具只加 handler"
    max_turns: int = 50,  # 最大循环轮次，作为兜底保险丝防止死循环
    on_tool_call: Callable[[str, dict, str], None] | None = None,  # 可选的回调钩子，用于打印/日志
) -> str:  # 返回循环退出的原因（finish_reason）
    """就地驱动 messages[] 直到模型停止调工具；返回退出时的 finish_reason。

    参数说明：
    - messages: 对话历史列表，函数会直接向其中追加 assistant 和 tool 消息
    - system: 系统提示词（会在每次 API 调用时插入到消息列表最前面）
    - tools: 传给 API 的工具定义列表（OpenAI function calling 格式）
    - handlers: 工具名到处理函数的映射字典，s02 起"加一个工具只加一个 handler"
    - max_turns: 兜底保险丝，防止模型陷入工具调用死循环
    - on_tool_call(name, input, output): 可选观测钩子，便于 REPL 打印工具调用过程
    """
    # 主循环：最多跑 max_turns 轮，每轮是一次 API 调用
    for turn in range(1, max_turns + 1):
        # 构造发送给 API 的消息列表：
        # 把系统提示词插入到最前面（OpenAI 格式把 system 作为 messages 的一部分，
        # 而不是像 Anthropic 那样作为单独的参数）
        api_messages = [{"role": "system", "content": system}] + messages

        # 调用 OpenAI 兼容的 Chat Completions API
        response = client.chat.completions.create(
            model=MODEL,  # 使用的模型（从环境变量读取，如 glm-5.1）
            messages=api_messages,  # 消息列表（含系统提示词 + 对话历史）
            tools=tools,  # 可用工具列表
            max_tokens=8000,  # 单次回复的最大 token 数
        )

        # 取出第一个（通常也是唯一一个）选择
        choice = response.choices[0]
        # 取出模型返回的消息对象
        msg = choice.message

        # 把模型的回复转成字典格式追加到对话历史中（assistant 角色）
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.content}
        # 如果模型调用了工具，把工具调用信息也加进去
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,  # 工具调用的唯一 ID，用于配对结果
                    "type": "function",  # 工具类型（目前只有 function）
                    "function": {
                        "name": tc.function.name,  # 函数名
                        "arguments": tc.function.arguments,  # 函数参数（JSON 字符串）
                    },
                }
                for tc in msg.tool_calls  # 遍历所有工具调用
            ]
        # 追加到对话历史
        messages.append(assistant_msg)

        # 如果 finish_reason 不是 "tool_calls"，说明模型不需要再调工具了，直接退出循环
        # 可能的值："stop"（正常结束）、"length"（达到 token 上限）等
        if choice.finish_reason != "tool_calls":
            return choice.finish_reason  # 返回退出原因

        # --- 以下是处理工具调用的逻辑 ---

        # 遍历模型返回的所有工具调用（同一轮可以调用多个工具）
        for tc in msg.tool_calls:
            # 从 handlers 字典中查找对应的处理函数
            handler = handlers.get(tc.function.name)

            # 解析模型传来的参数（OpenAI 格式下参数是 JSON 字符串，需要解析）
            try:
                args = json.loads(tc.function.arguments)  # 把 JSON 字符串解析成字典
            except json.JSONDecodeError:
                # 如果模型返回了无效的 JSON，用空字典兜底
                args = {}

            # 如果找到了处理函数就调用它，传入解析后的参数；
            # 如果没找到，返回错误提示（不会崩溃，优雅降级）
            output = (
                handler(**args)
                if handler
                else f"Error: no handler registered for tool '{tc.function.name}'"
            )

            # 如果提供了观测钩子回调，就调用它（用于在终端打印工具执行过程）
            if on_tool_call:
                on_tool_call(tc.function.name, args, output)

            # 把工具执行结果作为一条 role="tool" 的消息追加到对话历史
            # tool_call_id 必须和模型返回的 tc.id 对应，否则 API 会报错
            # 注意：OpenAI 格式下每个工具结果是一条独立消息（不像 Anthropic 打包在一个 user 消息中）
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": output}
            )

    # 如果循环跑满了 max_turns 轮还没退出，返回自定义的退出原因
    return "max_turns_exceeded"
