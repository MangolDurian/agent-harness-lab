# s02 学习笔记：Tool Use

> 格言：**加一个工具只加一个 handler。**

## 这一课到底在教什么

教"handlers dispatch 模式的可扩展性"：加一个工具只需要写一个工具模块 + 在 agent 入口注册，core/loop.py 一行不改。

```
                    handlers dispatch
                    ┌──────────────┐
  LLM ──tool_use──>│ name → run() │──> bash.run()
                    │              │──> read_file.run()
                    │              │──> write_file.run()
                    └──────────────┘
```

## 代码在哪

- `tools/read_file.py` —— 读文件工具
- `tools/write_file.py` —— 写文件工具
- `agents/s02_multi_tool.py` —— 组装入口（bash + read_file + write_file）
- `core/loop.py` —— **没改，一行都没改**

## s01 → s02 的改动量

| 文件 | 改动 |
|---|---|
| `core/loop.py` | 0 行 |
| `core/llm.py` | 0 行 |
| `tools/read_file.py` | 新增 |
| `tools/write_file.py` | 新增 |
| `agents/s02_multi_tool.py` | 新增（复制 s01 改 4 行） |

这就是 handlers dispatch 模式的威力：循环引擎完全不用动，加工具只是"写模块 + 注册 handler"。

## 我在学完后相对原版做的三个差异

| 差异 | 原版 | 我的做法 | 理由 |
|---|---|---|---|
| 路径安全 | 无限制 | `resolve()` + `startswith()` 工作目录边界检查 | 真实 harness 必须防止路径穿越，这是最基本的沙盒防护 |
| 工具数量 | 只加一个工具 | 一次加两个（read + write） | 比"加一个"更能体现"叠加"模式——加 N 个的步骤和加 1 个完全一样 |
| _print_tool_call 增强 | 统一格式 | 为每个工具定制可视化（read 显示路径，write 显示路径+行数） | 让终端输出更易读，也证明 agent 入口可以自由定制观测逻辑 |

## 四个必须能回答的问题

1. **为什么 `resolve()` 能防止路径穿越？**
   `resolve()` 会消除所有 `..` 和符号链接，得到真实绝对路径。之后用 `startswith()` 检查它是否在工作目录内，这样 `../../etc/passwd` 这类穿越就会被拦截。

2. **`mkdir(parents=True, exist_ok=True)` 为什么安全？**
   因为在调用它之前已经做了 `_resolve_safe()` 检查，所以 `target.parent` 一定在工作目录内（或就是工作目录本身）。`parents=True` 只会创建中间目录，不会穿越到工作目录之外。

3. **加第 N 个工具需要改 core/loop.py 吗？**
   不需要。只需要：① 写一个新模块（暴露 SCHEMA + run），② 在 agent 入口的 TOOLS 列表加一项、HANDLERS 字典加一条。loop.py 里的 `handlers.get(name)` 已经是通用的分发机制。

4. **如果模型传了一个不存在于 handlers 的工具名会怎样？**
   `handlers.get()` 返回 None，走到 `else` 分支，返回 `"Error: no handler registered for tool '...'"`。不会崩溃，模型会收到错误信息并自行决定下一步。这是优雅降级。

## 阶段成果验证

跑 `examples/s02_demo_prompts.md` 里的 4 个 prompt，每个对照预期现象打勾。
4 个都过 → s02 结业，可以进 s03。
