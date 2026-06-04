# s08: Background Tasks —— 慢操作丢后台，agent 继续想下一步

## 核心机制

s08 解决的问题：`pip install torch`、`docker build`、`npm install` 等命令动辄几十秒甚至几分钟。在阻塞的 agent_loop 里，agent 只能干等——loop.py 的 `handler(**args)` 是同步调用，handler 不返回，loop 就不往下走。

s08 的解法：**把慢命令丢到后台线程，handler 立即返回，agent 继续做别的。后台完成后，通过 handler wrapper 把结果"注入"到下一次工具调用输出中。**

## 新增文件

| 文件 | 说明 |
|---|---|
| `tools/background.py` | `BackgroundManager` 类 + 模块级单例函数 |
| `agents/s08_background.py` | s08 入口，含 background handler wrapper + 扩展 bash SCHEMA |

## 关键设计

### 1. 注入方式：handler 输出前缀

loop.py 的流程是：handler 执行 → `on_tool_call` 回调 → tool result 追加到 messages。我们不能在中间插入额外消息（会破坏 OpenAI 格式的 `tool_call_id` 配对）。

**方案**：所有 handler 经过一层 wrapper，每次调用前先收集已完成的后台任务，把通知文本拼接到本次 handler 输出的**前面**：

```
[后台任务 bg_1 完成] pip install torch
Successfully installed torch-2.x.x

<本次工具正常输出>
```

LLM 在下一次工具结果里就能看到后台通知，效果等同于注入。

### 2. 不修改 tools/bash.py

s08 在 agent 层创建一个扩展的 bash SCHEMA（`copy.deepcopy(bash.SCHEMA)` + 加 `run_in_background` 参数）。handler wrapper 拦截 `run_in_background=true`，不走 `bash.run()`，而是开线程。s01-s07 的 bash.py 不受影响。

### 3. BackgroundManager

- `start(func, command)` → 在 daemon 线程中执行 func，立即返回 bg_id
- `collect()` → 返回并清除所有已完成的任务
- `has_running()` → 是否有正在运行的后台任务
- `format_results(results)` → 格式化完成通知文本

线程安全：所有对 `_tasks` 的读写都通过 `_lock` 保护。

### 4. Post-loop flush：通知不卡住

通知在 handler wrapper 的 `collect()` 中取出，只在模型调工具时触发。但如果模型启动后台任务后只回文字就停了（`finish_reason="stop"`），通知就卡在管理器里出不来。

**解法**：REPL 的 `main()` 在 `agent_loop` 退出后，主动调 `background.collect()`。如果有已完成任务，注入一条 user 消息通知，再跑一轮 `agent_loop`（终止性见本节末尾说明）。

```
agent_loop → 模型停止 → collect() → 有完成通知？
  → 是：注入 user 消息，continue 再跑一轮
  → 否，但有 running 任务？→ 短超时轮询（最多 10 秒），等收尾后再 collect
  → 否：break，等用户下一条输入
```

注意：两轮 flush 之间如果又冒出新完成通知，会继续 flush。不做轮数硬上限，因为每轮必须通过 `agent_loop` 才能产生新的后台任务，而 flush 注入的 user 消息不会触发新后台任务（模型只是确认通知）。

### 已知边界

**10 秒上限**：轮询最多等 10 秒（`time.time() + 10`）。如果后台任务跑超过 10 秒（比如 `pip install torch`），post-loop flush 等不到就放弃，用户需要再开口问，模型调 `background_status` 才能拿到结果。这个上限是硬编码的，没有做可配置——教学项目够用，生产系统应该做成长轮询或事件驱动。

**轮询阻塞主线程**：`time.sleep(0.2)` 的轮询在 REPL 主线程里跑。轮询期间用户看到的现象是"模型回答完了但还没回到 `s08 >>` 提示符"——最多卡 10 秒。在 Web 端同样的阻塞发生在 `_run_agent_in_thread` 子线程里，不会卡 WebSocket 事件循环，但 `processing_end` 事件会延迟最多 10 秒才推到前端。如果后台任务远超 10 秒，用户体验和"不等"没有区别——该等的时候用户还得主动追问。

**Web 前端「一问一答」与输入排队**（`web/index.html`）：

- **旧行为**：`isProcessing` 为真时 `sendMessage()` 直接 return、发送按钮 `disabled`，用户只能干等本轮结束（含 post-loop 超时轮询），跟进消息无法输入或被丢弃。
- **现行为**：处理中仍可输入；消息进入 `pendingQueue`，输入框上方显示 `QUEUED` 提示条（可 `x` 取消）；本轮收到 `processing_end` 后按 FIFO 自动发出一条排队消息（再触发新一轮 `processing_start`）。断连或切换阶段会清空队列，避免跟进消息发进新上下文。
- **改善了什么**：不再"按钮置灰只能等"；例如后台 `sleep 8` 时用户可提前打好「装好了吗？」，第一轮一结束立刻自动发出，把跟进窗口用到最大。
- **没解决什么**：后端 `ws_endpoint` 处理一轮时会卡在内层事件循环排空队列，期间不 `receive` 新 WebSocket 消息——排队消息仍须等本轮（含轮询）结束才真正发到服务端，**无法在任务仍在跑时让模型当场处理第二条 user 消息**。因此 ≤10 秒的后台任务在 Web 端仍几乎没有「运行中」提问窗口（第一轮要等任务跑完才 `processing_end`）；要观测 `background_status` 的「运行中」分支，仍需任务 >10 秒（轮询 10 秒超时放弃、第一轮提前结束）且模型别用前台 `sleep` 自堵。若要「运行中就插话」，需改后端并发模型，超出当前教学范围。

### 5. background_status 工具：主动查询

加了 `background_status` 工具，让 agent 可以主动查后台任务状态。调这个工具时，wrapper 的 `collect()` 也会自动把已完成任务通知带出来——一次调用同时看到**完成通知 + 运行中任务**。

SYSTEM 提示词里明确告诉模型：用户问「装好了吗」时，用 `background_status` 确认，而不是凭记忆回答。

### 6. Handler 组装顺序

```
base handlers → background wrapper → nag wrapper
```

background wrapper 在最内层：拦截 `run_in_background` + 注入后台通知。
nag wrapper 在最外层：计数 + 提醒。

## 与 Claude Code 的对应关系

Claude Code 的 Bash 工具有 `run_in_background` 参数，执行长时间命令时设为 true，命令在后台运行。s08 复刻了这个机制。

## 相比原版的三个差异

| 差异 | 原版（Claude Code） | 本项目 |
|---|---|---|
| 后台通知注入 | 直接插入 assistant 消息 | handler wrapper 输出前缀（不改 loop） |
| 后台任务管理 | 内建调度系统 | 简单的 threading + dict（daemon 线程） |
| 扩展 bash 参数 | 修改 bash 工具定义 | deepcopy SCHEMA + agent 层扩展 |
