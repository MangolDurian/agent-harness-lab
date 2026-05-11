# s04 学习笔记：Subagent —— 大任务拆小，每个小任务干净的上下文

## 这一课新加的机制

### 1. delegate 工具（tools/subagent.py）

让主 agent 能把子任务委托给独立的子 agent 执行。

核心原理：`delegate(task)` 启动一个**嵌套的 `agent_loop`**，拥有全新的消息历史和独立的工具集。子 agent 执行完毕后，结果作为工具输出返回给主 agent。

关键设计：
- **干净上下文**：子 agent 只看到 `task` 这一条消息，看不到主 agent 的对话历史
- **防递归**：子 agent 只有 bash / read_file / write_file，没有 delegate，不能再生子 agent
- **轮次限制**：子 agent 最多跑 20 轮（比主 agent 的 50 轮少），防止失控

### 2. 子 agent 可视化

通过 `set_subagent_callback()` 设置子 agent 的工具调用回调，用缩进 + 灰色区分层级：
- 主 agent 工具调用：黄色，无缩进
- 子 agent 工具调用：灰色，`  >` 前缀

回调通过模块级变量传递，因为 `run()` 的签名被 handler dispatch 约束为 `run(task) -> str`。

### 3. 主 agent 的 delegate 可视化

`_print_tool_call` 为 `delegate` 工具特别展示：显示被委托的任务摘要和返回结果。

## 相比原版的三个差异

| 差异 | 原版 | 本项目 | 理由 |
|---|---|---|---|
| 子 agent 定义位置 | 内联在 agent 入口中 | `tools/subagent.py` 独立模块 | 保持 tools/ 目录一致性 |
| 回调传递方式 | 直接传参 | 模块级变量 `set_subagent_callback()` | `run()` 签名被 handler dispatch 约束 |
| 层级可视化 | 无特殊区分 | 缩进 + 灰色 vs 黄色 | 多层调用时便于区分主/子 |

## 关键领悟

1. **嵌套 agent_loop = 嵌套思维**。子 agent 的 `agent_loop` 是嵌套调用——外层循环在等 delegate 工具返回时被阻塞。这是同步的、深度优先的委托模型。

2. **干净上下文是最重要的属性**。子 agent 看不到主 agent 的对话历史，这意味着：主 agent 的系统提示词、之前的工具输出、用户的原始请求——子 agent 全都不知道。好处是不会污染，坏处是需要把所有必要信息写在 `task` 参数里。

3. **防递归是安全底线**。如果子 agent 也有 delegate 工具，理论上可以无限嵌套。通过限制子 agent 的工具集来防止这种情况。
