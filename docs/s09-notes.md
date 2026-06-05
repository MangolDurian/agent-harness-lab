# s09: Agent Teams —— 任务太大一个人干不完，要能分给队友

## 核心机制

s09 把 s04 的一次性 delegate 升级为**持久化的队友系统**：

| 维度 | s04 delegate | s09 队友 |
|---|---|---|
| 生命周期 | 一次性，干完就死 | 持久，working/idle 循环，poll inbox 等新任务 |
| 身份 | 无 | 有 name + role |
| 并发 | 阻塞主 agent | 独立线程并发 |
| 通信 | 返回结果给主 agent | JSONL inbox 消息总线，双向通信 |
| 可复用 | 不可 | idle 后 send 新任务会自动唤醒 |

### 三个新工具

1. **spawn(name, role, prompt)**：创建队友，启动独立线程跑 `_teammate_loop`
2. **send(to, content)** / **broadcast(content)**：消息通信
3. **team_status()**：查看团队状态

### 队友的生命周期（核心变化）

队友线程跑的是 **working → idle → poll inbox → working** 的循环：

1. spawn 时收到初始 prompt，进入 working 状态跑 `agent_loop`
2. 任务完成（模型停止调工具）→ 汇报 lead → 状态改 idle
3. idle 状态下每秒 poll inbox
4. 收到新消息 → 重新进入 working，用干净上下文跑 `agent_loop`
5. 只有收到 `__shutdown__` 才退出线程

### 消息注入

- **自动注入**：background wrapper 每次工具调用前 drain lead inbox，拼到后台通知前面
- **REPL 等待**：post-loop flush 会短超时轮询（15 秒），等队友完成消息，类似 s08 等后台任务
- **主动查看**：lead 也可以通过 send 发新任务给 idle 队友

### 防护

- 队友名字校验：禁止 lead/system 等保留名，只允许字母数字下划线连字符
- send() 校验接收者存在
- inbox 输出截断到 50000 字符

## 相比原版的三个差异

| 差异 | 原版（s04 delegate） | 本项目（s09 队友） |
|---|---|---|
| 并发模型 | 阻塞主 agent，等子 agent 完成 | 独立线程并发，lead 可继续工作 |
| 通信方式 | 子 agent 返回结果给主 agent | JSONL inbox 消息总线，双向通信 |
| 生命周期 | 一次性，用完即弃 | 持久化，working/idle 循环，可复用 |

## 关键代码路径

- `tools/team.py`：TeammateManager + 4 个 SCHEMA + 模块级函数
- `agents/s09_agent_teams.py`：入口脚本，background wrapper 增加 inbox 注入
- 队友线程通过 `_teammate_loop` → `_run_one_task` 跑独立的 `agent_loop`
- idle 后 poll inbox 等新任务，不会退出
- 队友的 `send` 通过 closure 绑定 sender 名字
