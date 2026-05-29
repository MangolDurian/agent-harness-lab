# s06: Context Compact —— 上下文总会满，要有办法腾地方

## 核心问题

Agent 的对话历史（messages）会持续增长，最终撑爆 LLM 的上下文窗口。必须有机制在运行中"腾地方"，让 agent 能长时间运行而不溢出。

## 三层压缩策略

### Layer 1: micro_compact（静默，每轮自动）

每次工具调用后自动执行。将超过 3 轮的 `tool` 消息内容替换为 `[已压缩：{前100字}...]`。

原理：
1. 遍历 messages，按 `assistant(tool_calls)` 划分工具轮次
2. 计算每个 tool 消息属于哪轮
3. 替换旧轮次（超过 3 轮前）的 tool 输出为占位符

特点：不动 user/assistant 消息，只压缩 tool 输出。

### Layer 2: auto_compact（阈值触发 / 手动触发）

估算 token 数（`len(json.dumps(messages)) / 4`），超过 20000 时触发。

流程：
1. 估算总 token 数
2. 验证至少有 5 个工具轮次（保留 3 + 当前 1 = 4，至少还要 1 个可压缩）
3. 找分割点：保留最近 3 轮 + 当前轮不动
4. 格式化旧消息为可读文本
5. 调用 LLM 生成摘要（独立 API 调用）
6. 用 `[上下文摘要]` user + `[已读取摘要]` assistant 消息对替换旧部分

安全约束：
- 绝不删除当前轮的 assistant 消息（含 tool_calls）
- 绝不删除当前轮的 tool 结果（tool_call_id 配对）
- 分割点之后的所有消息原样保留
- 如果分割点后紧接着 assistant 消息，插入 bridge user `[继续执行任务]` 维持交替

为什么阈值是 20000 而不是 50000？micro_compact 持续压缩旧轮次，
将 tool 输出总 token 控制在 `3 轮 × 单次输出` 以内。50000 的阈值在
micro_compact 运作下几乎不可能达到。20000 更实际，既能在
大输出场景（bash 近 50K 字符输出）下可靠触发，又不会在正常使用中误触发。

### Layer 3: compact 工具（手动触发）

Agent 主动调用 `compact` 工具 → handler 设置 `_compact_requested` flag → on_tool_call 检测到 flag → 强制触发 auto_compact。

## 集成方式：on_tool_call 回调 + closure

原版 s06 直接修改 `agent_loop` for 循环头部，插入 micro_compact/auto_compact 逻辑。我们的约束是 **core/loop.py 一行不改**。

利用 `on_tool_call(name, args, output)` 回调：
- 它在 handler 执行后、tool result 追加到 messages 之前触发
- 通过 closure 持有 `messages` 引用
- 可以在每轮工具调用后原地修改 messages
- 下一轮 API 调用自然读到压缩后的 messages

```python
def _make_compacting_callback(messages):
    def callback(name, args, output):
        _print_tool_call(name, args, output)
        compact.check_and_compact(messages)
    return callback
```

## 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 压缩触发位置 | 修改 agent_loop for 循环头部 | on_tool_call 回调 + closure 访问 messages |
| compact 工具执行 | 直接在 loop 内检查并调用压缩 | handler 设置 flag + on_tool_call 检查 flag 并执行 |
| auto_compact 摘要格式 | 单条 system reminder | user+assistant 消息对（兼容 OpenAI 格式交替要求） |

## 关键设计决策

1. **为什么用 user+assistant 而不是 system reminder？** OpenAI API 要求消息角色交替出现（user → assistant → user → ...），单条 system reminder 可能打破这个规则。user+assistant 对是最安全的格式。

2. **为什么 compact.run() 不直接执行压缩？** on_tool_call 回调发生在 handler 执行后、当前 tool result 追加进 messages **之前**。所以 check_and_compact(messages) 看到的状态是："当前 assistant(tool_calls) 已在 messages 中，但当前 tool output 还没追加"。compact.run() 设置 flag，等 on_tool_call 统一处理——此时当前 tool result 尚未入列，不会干扰 auto_compact 的消息替换。如果把压缩逻辑放在 run() 里，run() 的返回值还没作为 tool result 进入 messages，同时 auto_compact 却在原地修改 messages，两者交叉容易导致不一致。

3. **token 估算为什么用字符数/4？** 这是中英混合文本的粗略经验值。精确计算需要 tokenizer，但引入额外依赖不值得。粗估足以判断"是否该压缩了"。
