# s03 学习笔记：TodoWrite —— 没有计划的 agent 走哪算哪

## 这一课新加的机制

### 1. TodoManager（tools/todo.py）

任务追踪器，让 agent 能记录待办事项、标记进度。

- **全量替换模式**：每次调用 `todo_write` 都传入完整的 todo 列表，不是增量更新
- **状态三态**：`pending` → `in_progress` → `completed`
- **约束**：同一时刻最多只有一项 `in_progress`
- **自动编号**：`replace()` 自动分配递增 id

### 2. Nag 提醒机制（agents/s03_todo.py 的 `_make_nagging_handlers`）

**这是本课的核心创新点。**

原版 learn-claude-code 的 nag 是通过修改 `agent_loop` 内部实现的——往 messages 列表里注入 system reminder。
我们的做法完全不同：用 **handler wrapper 闭包** 实现 nag，不动 core/loop.py 一行代码。

原理：
- 用闭包变量 `tool_calls_since_todo` 跟踪连续未调用 `todo_write` 的工具调用次数
- 所有非 `todo_write` 的 handler 被包装：调用后计数 +1，超过阈值时在输出尾部追加提醒
- `todo_write` handler 被单独包装：调用后计数归零

注意：这里统计的是"工具调用次数"而非"模型轮次"。如果同一轮模型并发调用多个工具，每个都会 +1。这样命名（`tool_calls_since_todo`）更准确，也符合"不改 core"的路线——真按轮次统计需要改 core/loop.py。

关键技巧：`tool_calls_since_todo = [0]` 用 list 包裹，因为 Python 闭包不能直接赋值外层变量（nonlocal 也行，但 list 更直观）。

### 3. Todo 可视化

`_print_tool_call` 为 `todo_write` 定制了展示格式，显示任务总数和各状态统计。

## 相比原版的三个差异

| 差异 | 原版 | 本项目 | 理由 |
|---|---|---|---|
| Nag 实现方式 | 修改 agent_loop 内部，往 messages 注入 system reminder | handler wrapper 闭包，追加到工具输出尾部 | 不动 core/loop.py 是铁律 |
| 代码组织 | 单文件，TodoManager 和 handler 都内联 | `tools/todo.py` 独立模块 + `agents/` 组装 | 保持 handlers dispatch 模式一致性 |
| Todo schema 格式 | Anthropic input_schema | OpenAI function calling format | 与项目其他工具保持统一 |

## 关键领悟

1. **Agent 的"记忆"不只是对话历史**。Todo 列表是一种结构化的外部记忆，比纯文本更可靠——模型知道该做什么、做到了哪一步。

2. **Nag 本质上是给模型一个"外部时钟"**。没有 nag，模型可能在连续调用工具时忘记更新计划；有 nag，模型被定期提醒要回头看计划。

3. **闭包 wrapper 是一种强大的中间层模式**。它能在不修改 core 的情况下注入行为（计数、提醒、重置），是"分层架构"的好例子。
