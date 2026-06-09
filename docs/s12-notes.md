# s12 Worktree Isolation 学习笔记

## 格言

**各干各的目录，互不干扰。**

## 问题

s09-s11 所有任务共享一个工作目录。两个队友同时改 `config.py`，改动互相污染，谁也没法干净回滚。任务板管"做什么"但不管"在哪做"。

## 解法：Worktree 隔离

给任务绑定独立的 git worktree 目录。每个 worktree 是一个独立的 git 工作目录，有自己的分支，文件改动完全隔离。

### 双面架构

```
Control plane (data/tasks.json)    Execution plane (.worktrees/)
+------------------+               +------------------------+
| #1 [~] @alice    |               | auth-refactor/         |
|   worktree: "auth-refactor" <--> | branch: wt/auth-refactor|
+------------------+               | task_id: 1              |
| #2 [ ]           |               +------------------------+
|   worktree: null |               | ui-login/              |
+------------------+               | branch: wt/ui-login     |
                                   | task_id: 2              |
                                   +------------------------+
                                   index.json (registry)
                                   events.jsonl (lifecycle)
```

### 状态机

- Task: `pending → in_progress → completed`（不变）
- Worktree: `absent → active → removed | kept`

## 新增机制

### 1. WorktreeManager（tools/worktree.py）

管理 worktree 的完整生命周期：

- `create(name, task_id?)`：创建 git worktree + 绑定任务
- `remove(name, force?, complete_task?)`：删除 worktree + 可选完成任务
- `keep(name)`：标记为 kept，不被自动清理
- `list_worktrees()`：列出所有 worktree 及状态
- `exec_command(name, command)`：在 worktree 中执行命令

存储：
- `.worktrees/index.json`：注册表
- `.worktrees/events.jsonl`：生命周期事件日志

### 2. 任务-Worktree 绑定

task.py 新增：
- 任务对象新增 `worktree` 字段（string，默认 null）
- `_format_task()` 显示 `[wt:name]` 标记
- `bind_worktree(task_id, name)`：绑定 worktree
- `unbind_worktree(task_id)`：解除绑定
- `claim()`：认领时如果任务有 worktree，返回信息中提示

### 3. 队友执行隔离

team.py 增强：
- 队友认领绑定 worktree 的任务时，构造的 prompt 包含 worktree 信息
- 工厂函数 `make_worktree_bash_handler(worktree_path)` 等，替换默认 handler
- 无需修改 core/loop.py

### 4. 5 个新工具

| 工具 | 功能 |
|---|---|
| worktree_create | 创建 worktree 并可选绑定任务 |
| worktree_remove | 删除 worktree（可选完成任务） |
| worktree_keep | 保留 worktree |
| worktree_list | 列出所有 worktree |
| worktree_exec | 在 worktree 中执行命令 |

## 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 任务存储 | `.tasks/task_N.json` 每任务单文件 | 保持 `data/tasks.json` 统一文件 + 新增 `worktree` 字段 |
| 执行隔离方式 | 修改 loop 层传入 cwd | 工厂函数创建 worktree-aware 的 bash/read/write handler |
| Worktree 粒度 | 全局 worktree exec | 队友认领绑定 worktree 的任务时自动隔离 |

## 关键设计决策

### 为什么用工厂函数而不是修改 loop？

core/loop.py 的约束。工厂函数模式让 handler 在创建时就绑定了正确的 cwd，不需要 loop 知道 worktree 的存在。

### 为什么 worktree 注册表用 JSON 而不是 git 命令？

`git worktree list` 可以列出 worktree，但不包含 task_id 绑定和 kept 状态。用 JSON 注册表可以存储这些元数据，同时 git 命令处理实际的目录操作。

### 为什么 events.jsonl 是追加写入？

生命周期事件（created/removed/kept）用 append-only 日志，方便审计和调试，也避免并发写入时的冲突。
