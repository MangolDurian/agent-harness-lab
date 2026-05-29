"""compact 工具 —— 三层上下文压缩。

核心挑战：上下文总会满，要有办法腾地方。
本项目约束 core/loop.py 一行不改，所以通过 on_tool_call 回调
在每轮工具调用后原地修改 messages 来实现压缩。

三层策略：
  Layer 1: micro_compact — 每轮静默压缩旧 tool 输出为占位符
  Layer 2: auto_compact  — token 超阈值时，LLM 摘要替换旧消息
  Layer 3: compact 工具  — 手动触发 auto_compact
"""
from __future__ import annotations

import json

from core.llm import MODEL, client

# ---- 配置常量 ----
_MICRO_KEEP_TURNS = 3       # micro_compact 保留最近 N 轮的完整 tool 输出
_AUTO_TOKEN_THRESHOLD = 20000  # auto_compact 触发的 token 估算阈值
_AUTO_KEEP_TURNS = 3          # auto_compact 保留最近 N 轮 + 当前轮不动
_SUMMARY_MAX_TOKENS = 2000    # 摘要生成的最大 token 数

# ---- 模块状态 ----
# 用 dict 而非裸变量，避免 global 声明问题（mutate vs rebind）
_state = {"compact_requested": False}


def reset_state() -> None:
    """重置模块状态。测试或 REPL 重新开始时调用。"""
    _state["compact_requested"] = False

# ---- SCHEMA ----

SCHEMA = {
    "type": "function",
    "function": {
        "name": "compact",
        "description": (
            "手动压缩上下文。当对话历史过长、感觉信息冗余、"
            "或模型似乎遗忘早期信息时调用。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


# ---- 工具入口 ----


def run() -> str:
    """compact 工具的 handler：设置 flag，等 on_tool_call 检查时触发。"""
    _state["compact_requested"] = True
    return "已标记压缩请求，将在本轮工具调用后执行压缩。"


# ---- 辅助函数 ----


def _estimate_tokens(messages: list) -> int:
    """粗略估算 token 数：字符数 / 4（中英混合的平均水平）。"""
    return len(json.dumps(messages, ensure_ascii=False)) // 4


def _find_tool_turns(messages: list) -> list[int]:
    """找到所有 assistant+tool_calls 消息的索引（即工具轮次起点）。

    每个工具轮次的结构：assistant(tool_calls) → tool → tool → ...
    """
    return [
        i for i, m in enumerate(messages)
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]


# ---- Layer 1: micro_compact（静默，每轮自动）----


def micro_compact(messages: list) -> int:
    """将超过 N 轮的 tool 输出替换为占位符，释放上下文空间。

    只压缩 tool 消息的 content，不动 assistant 和 user 消息。
    保留最近 _MICRO_KEEP_TURNS 轮的完整输出，更早的替换为
    "[已压缩：{前100字}...]"。

    返回被压缩的消息数量。
    """
    turn_indices = _find_tool_turns(messages)
    if len(turn_indices) <= _MICRO_KEEP_TURNS:
        return 0

    # 当前轮是最后一个工具轮次
    current_turn = len(turn_indices) - 1
    # 需要压缩的轮次：比 (当前 - _MICRO_KEEP_TURNS) 更早的
    old_turn_limit = current_turn - _MICRO_KEEP_TURNS

    compressed = 0
    for turn_i in range(old_turn_limit + 1):
        assistant_idx = turn_indices[turn_i]
        # 获取本轮的 tool_call_id 集合
        tc_ids = {
            tc["id"]
            for tc in messages[assistant_idx].get("tool_calls", [])
        }

        # 遍历 assistant 后续的 tool 消息（OpenAI 格式下它们是连续的）
        for j in range(assistant_idx + 1, len(messages)):
            msg = messages[j]
            if msg.get("role") != "tool":
                break
            if msg.get("tool_call_id") in tc_ids:
                content = msg.get("content", "")
                if len(content) > 200 and not content.startswith("[已压缩："):
                    msg["content"] = f"[已压缩：{content[:100]}...]"
                    compressed += 1

    return compressed


# ---- Layer 2: auto_compact（阈值触发 / 手动触发）----


def _format_messages_for_summary(messages: list) -> str:
    """将消息列表格式化为可读文本，供 LLM 生成摘要。"""
    lines = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")

        if role == "user":
            lines.append(f"用户: {content}")
        elif role == "assistant":
            if content:
                lines.append(f"助手: {content}")
            for tc in msg.get("tool_calls", []):
                fn = tc["function"]["name"]
                args_str = tc["function"]["arguments"]
                lines.append(f"  调用工具: {fn}({args_str})")
        elif role == "tool":
            preview = content[:200] if len(content) > 200 else content
            lines.append(f"  工具结果: {preview}")

    return "\n".join(lines)


def _generate_summary(formatted_text: str) -> str:
    """调用 LLM 生成对话摘要。"""
    prompt = (
        "请简洁总结以下对话历史的关键信息，保留：\n"
        "1. 用户的原始请求和意图\n"
        "2. 已完成的关键操作和结果\n"
        "3. 重要的中间发现或决策\n"
        "忽略冗余的工具输出细节。用中文回答，300字以内。\n\n"
        f"--- 对话历史 ---\n{formatted_text}"
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=_SUMMARY_MAX_TOKENS,
    )
    return response.choices[0].message.content or "(摘要生成失败)"


def auto_compact(messages: list) -> bool:
    """用 LLM 摘要替换旧消息，腾出上下文空间。

    安全约束（绝对不能动的东西）：
    - 当前轮的 assistant 消息（含 tool_calls，删了 API 报错）
    - 当前轮已追加的 tool 结果（tool_call_id 配对）
    - 分割点之后的所有消息

    替换格式：user+assistant 消息对（兼容 OpenAI 格式交替要求）。
    如果分割点之后紧接着是 assistant 消息，额外插入一条 bridge user 消息维持交替。

    返回是否执行了压缩。
    """
    turn_indices = _find_tool_turns(messages)

    # 需要 _AUTO_KEEP_TURNS + 2 个轮次：保留 _AUTO_KEEP_TURNS + 1（含当前），
    # 至少还要 1 个轮次可以压缩
    if len(turn_indices) <= _AUTO_KEEP_TURNS + 1:
        return False

    # 保留区域的起点：最近 _AUTO_KEEP_TURNS 轮 + 当前轮
    keep_from_turn = turn_indices[-(_AUTO_KEEP_TURNS + 1)]

    # 回溯找到该轮之前最近的一条 user 消息，作为分割点
    # 停在 index 1（不含 0），确保 split_idx > 0
    split_idx = 0
    for i in range(keep_from_turn - 1, 0, -1):
        if messages[i].get("role") == "user":
            split_idx = i
            break

    if split_idx == 0:
        # 回退方案：直接在 keep_from_turn 处分割，
        # 用 bridge user 消息维持 OpenAI 格式交替
        split_idx = keep_from_turn
        need_bridge = messages[split_idx].get("role") == "assistant"
    else:
        need_bridge = False

    if split_idx == 0:
        return False  # 极端情况：只有一条消息，无法压缩

    # 格式化旧消息 → 生成摘要
    old_messages = messages[:split_idx]
    formatted = _format_messages_for_summary(old_messages)

    try:
        summary = _generate_summary(formatted)
    except Exception as e:
        print(f"\033[90m[auto_compact] 摘要生成失败: {e}\033[0m")
        return False

    # 构造替换消息（user+assistant 维持 OpenAI 格式交替要求）
    replacement = [
        {"role": "user", "content": f"[上下文摘要]\n{summary}"},
        {"role": "assistant", "content": "[已读取摘要]"},
    ]
    if need_bridge:
        replacement.append({"role": "user", "content": "[继续执行任务]"})

    messages[:split_idx] = replacement

    return True


# ---- 集成入口（on_tool_call 中调用）----


def check_and_compact(messages: list) -> None:
    """在 on_tool_call 回调中调用：执行 micro + 检查 auto。

    这是三层压缩的总调度入口，每次工具调用后都会被调用。
    """
    # Layer 1: 始终执行 micro_compact（静默压缩旧 tool 输出）
    compressed = micro_compact(messages)
    if compressed > 0:
        print(f"\033[90m[micro_compact] 压缩了 {compressed} 条旧工具输出\033[0m")

    # Layer 2/3: 检查是否需要 auto_compact
    need_auto = (
        _state["compact_requested"]
        or _estimate_tokens(messages) > _AUTO_TOKEN_THRESHOLD
    )
    if not need_auto:
        return

    reason = "手动请求" if _state["compact_requested"] else "token 超阈值"
    old_tokens = _estimate_tokens(messages)
    print(f"\033[90m[auto_compact] 触发压缩（{reason}，估算 ~{old_tokens} tokens）\033[0m")

    if auto_compact(messages):
        new_tokens = _estimate_tokens(messages)
        print(f"\033[90m[auto_compact] 完成，{old_tokens} → {new_tokens} tokens\033[0m")
    else:
        print("\033[90m[auto_compact] 轮次不足，跳过\033[0m")

    _state["compact_requested"] = False
