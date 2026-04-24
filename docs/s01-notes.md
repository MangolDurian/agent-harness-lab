# s01 学习笔记：Agent Loop

> 格言：**One loop & Bash is all you need.**

## 这一课到底在教什么

教"让模型能碰到真实世界"的最小机制：

```
+--------+      +-------+      +---------+
|  User  | ---> |  LLM  | ---> |  Tool   |
| prompt |      |       |      | execute |
+--------+      +---+---+      +----+----+
                    ^                |
                    |  tool_result   |
                    +----------------+
                    (loop until stop_reason != "tool_use")
```

## 代码在哪

- `core/loop.py` —— 地基循环，12 课都不改
- `core/llm.py` —— Anthropic 客户端单点管理
- `tools/bash.py` —— 第一双手
- `agents/s01_agent_loop.py` —— 组装入口

## 我在学完后相对原版做的三个差异（证明不是抄的）

| 差异 | 原版 | 我的做法 | 理由 |
|---|---|---|---|
| 工具分发 | `run_bash(block.input["command"])` 硬调 | `handlers: dict[str, Callable]` dispatch map | 为 s02 "加一个工具只加一个 handler" 预埋接口，s02 改动量 = 0 |
| 循环边界 | `while True` 永远转 | `for turn in range(max_turns)` + 返回 `stop_reason` | 真实 harness 都需要兜底保险丝，防止模型在工具调用里死循环 |
| 分层 | 单文件 | `core / tools / agents` 三层 | 体现"循环不变、机制叠加"——这是整条学习路线的底层信念 |

## 四个必须能回答的问题

1. **messages[] 有哪几种角色？每种的 content 是什么结构？**
   - `user` 的 content 可以是纯字符串，也可以是一个 list，里面装 `tool_result` 块
   - `assistant` 的 content 永远是 list，里面装 `text` 块和/或 `tool_use` 块

2. **为什么 tool_result 作为 `role=user` 发回去？**
   Anthropic API 的约定：tool_result 归属在 user turn 里（它代表"环境/harness 回给模型的东西"，不是新角色）。同一轮里多个工具结果打包进同一个 user 消息即可。

3. **去掉 `stop_reason != "tool_use"` 判断会怎样？**
   如果模型这轮本来只想回句话（stop_reason=end_turn），你没退出，就会在没有 tool_result 的情况下再发一次，API 立即 400。

4. **一轮里多个 tool_use 只执行一个会怎样？**
   下一次请求里，API 会发现 assistant 的 tool_use_id 和 user 的 tool_result 对不上 → 400。
   **所以必须在同一个 user turn 里把这一轮所有 tool_use 都配对响应完。**

## 阶段成果验证

跑 `examples/s01_demo_prompts.md` 里的 4 个 prompt，每个对照预期现象打勾。
4 个都过 → s01 结业，可以进 s02。
