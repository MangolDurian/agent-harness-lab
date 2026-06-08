# s11: Autonomous Agents —— 队友自己看看板，有活就认领

## 核心机制

s11 让队友从"被动等分配"变成"主动找活干"。

### 三个新能力

1. **自主扫描**：队友空闲时自动扫描任务板，发现无主 pending 任务就构造 prompt 让 LLM 通过 `task_claim` 认领
2. **任务所有权**：任务新增 `owner` 字段，`task_claim` 原子认领（设 owner + status=in_progress），`task_complete` 仅 owner 可完成
3. **空闲超时**：队友空闲超过 60 秒无工作，自动发消息给 lead 并退出

### 设计理念：基础设施扫描，LLM 认领

关键设计决策：`_teammate_loop` 的 idle 循环直接调 `task._manager.find_claimable()` 找任务，
但找到后**不是基础设施直接 claim**，而是构造 prompt 让 LLM 通过 `task_claim` 工具认领。

这保持了 s09 以来的核心模式："队友只通过工具操作"。

**机制边界**：自主认领仍是 LLM 软执行（LLM 可能选择不 claim），硬保证来自 `task_claim` 的工具层状态机：
- `find_claimable()` 返回快照，不占位——两个队友可能拿到同一批可认领任务
- `claim()` 内部用 `threading.RLock()` 保护读-改-写流程，多队友并发认领同一任务只有一个成功
- 每个 owner 的 in_progress 互斥在 claim 内强制校验

### in_progress 约束放宽

- s07-s10：全局只能有 1 个 in_progress
- s11：**每个 owner 一个 in_progress 槽**
- owner=None（lead 的无主任务）仍全局 1 个
- 多个队友可以并行各自做自己的任务

## 新增工具

| 工具 | 谁用 | 作用 |
|---|---|---|
| `task_claim` | Teammate | 原子认领：设 owner + status=in_progress |
| `task_complete` | Teammate | 完成任务：设 status=completed（仅 owner 可完成） |

Lead 仍用 `task_create` / `task_update` / `task_list`。

## idle 循环流程

```
队友完成任务 → idle
  ├─ poll inbox（优先级 1，和 s10 一样）
  ├─ scan 任务板（优先级 2，s11 新增）
  │   └─ 找到无主 pending → 构造认领 prompt → LLM 调 task_claim
  └─ 超时 60s 无工作 → 自主退出（发消息给 lead）
```

## 线程安全

s11 的核心场景是多队友并发认领任务。`TaskManager` 用 `threading.RLock()` 保护所有读-改-写操作：
- `create`、`update`、`claim`、`complete`、`find_claimable` 都在锁内执行
- 用 `RLock`（可重入锁）而非 `Lock`，因为 `claim/complete` 内部调 `format()` → `_summary()` 也读 `_tasks`
- `_save()` 的原子写入（.tmp → rename）在锁内完成，杜绝并发写 `tasks.tmp` 导致的 `FileNotFoundError`

## 改动文件

- `tools/task.py`：owner 字段、claim()、complete()、find_claimable()、in_progress 放宽、RLock 线程安全
- `tools/team.py`：idle 扫描、超时退出、队友任务工具（configure_autonomous）
- `agents/s11_autonomous_agents.py`：新 agent 入口

## 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 认领机制 | 基础设施直接 claim + 执行 | 基础设施扫描但构造 prompt 让 LLM 调 task_claim——保持"队友只通过工具操作"模式 |
| in_progress 约束 | 全局单 in_progress + 文件锁 | 按 owner 的 in_progress 槽——多个队友可并行工作 |
| 空闲超时 | 独立计时器线程或事件 | idle_start 时间戳嵌入现有 poll 循环——无新线程、无新事件 |
