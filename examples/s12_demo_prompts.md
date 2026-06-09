# s12 Worktree Isolation 验证 Prompt

本 demo 按顺序跑。s12 的重点不是"多一个文件工具"，而是验证：

```text
任务板负责分配任务，worktree 负责隔离执行目录。
```

## 前置清理

在启动 s12 前先清理历史状态。这里要同时清理 `.team`、任务板、`.worktrees` 目录、git worktree metadata 和 `wt/*` 分支。

```bash
source .venv/bin/activate
git worktree prune 2>/dev/null
for b in $(git branch --format='%(refname:short)' | grep '^wt/' || true); do
  git branch -D "$b" 2>/dev/null || true
done
rm -rf .team data/tasks.json .worktrees run-outputs/s12
python agents/s12_worktree_isolation.py
```

## 验证 1：创建任务并绑定 worktree

**Prompt：**

```text
请按顺序执行：
1. 创建两个任务：
   - 在绑定的 worktree 中写 auth_note.txt，内容为 "auth isolated"
   - 在绑定的 worktree 中写 ui_note.txt，内容为 "ui isolated"
2. 创建 worktree "auth-refactor" 并绑定任务 1。
3. 创建 worktree "ui-login" 并绑定任务 2。
4. 用 task_list 和 worktree_list 查看结果。
```

**预期：**

- `task_list` 显示两个任务。
- 任务 1 带 `[wt:auth-refactor]`。
- 任务 2 带 `[wt:ui-login]`。
- `worktree_list` 显示两个 active worktree。

## 验证 2：显式隔离执行

**Prompt：**

```text
请用 worktree_exec 做隔离验证：
1. 在 auth-refactor worktree 中创建 manual_auth.txt，内容为 "manual auth"。
2. 在 ui-login worktree 中创建 manual_ui.txt，内容为 "manual ui"。
3. 检查主目录下是否存在 manual_auth.txt 或 manual_ui.txt。
4. 再分别在两个 worktree 中读取对应文件内容。
```

**预期：**

- `worktree_exec("auth-refactor", ...)` 成功写入 `manual_auth.txt`。
- `worktree_exec("ui-login", ...)` 成功写入 `manual_ui.txt`。
- 主目录没有 `manual_auth.txt` 和 `manual_ui.txt`。
- 两个 worktree 内能读到各自文件。

## 验证 3：队友通过 idle scan 自动进入 worktree

**Prompt：**

```text
spawn 一个队友 alice（coder），让她先等待任务板，不要在初始 prompt 里直接写文件。
让她空闲后自动扫描任务板，发现任务 1 后自己认领并完成。
```

**预期：**

- alice 初始 prompt 结束后进入 idle。
- idle scan 发现任务 1。
- alice 调用 `task_claim("1")`。
- 因任务 1 绑定了 `auth-refactor`，alice 的 `bash/read_file/write_file` 被替换为 worktree-aware handler。
- alice 写出的 `auth_note.txt` 落在 `.worktrees/auth-refactor/`，不是主目录。
- alice 完成后用 `send` 汇报 lead。

**关键边界：**

这条 demo 必须走 idle scan 路径。直接在 `spawn` 初始 prompt 中让 alice 写文件，不能证明 handler 自动替换生效。

## 验证 4：检查队友隔离结果

**Prompt：**

```text
查看 task_list 和 team_status。
然后检查：
1. 主目录下有没有 auth_note.txt。
2. auth-refactor worktree 中有没有 auth_note.txt，并读取内容。
```

**预期：**

- 任务 1 显示为 completed，owner 是 `@alice`。
- alice 最终是 idle 或 stopped。
- 主目录没有 `auth_note.txt`。
- `auth-refactor` worktree 中存在 `auth_note.txt`，内容是 `auth isolated`。

## 验证 5：keep/remove 生命周期

**Prompt：**

```text
对 ui-login worktree 执行 keep。
然后删除 auth-refactor worktree，并设置 force=true、complete_task=true。
最后用 worktree_list 和 task_list 查看。
```

**预期：**

- `ui-login` 状态变为 `[kept]`。
- `auth-refactor` 即使有未提交文件，也会被强制删除并变为 `[removed]`。
- 如果任务 1 尚未完成，`complete_task=true` 会把它完成；如果已完成，结果仍应保持 completed。
- 任务 2 仍绑定 `ui-login`，但 worktree 状态是 kept。

## 验证 6：事件流

**Prompt：**

```text
用 bash 查看 .worktrees/events.jsonl 的内容。
```

**预期：**

- 能看到 `created` 事件。
- 能看到 `kept` 事件。
- 能看到 `removed` 事件。
- 每条事件有 `timestamp` 和 `data`。

## 验证 7：s11 兼容路径，不绑定 worktree 也能自治

**Prompt：**

```text
创建任务 3：在 run-outputs/s12/plain_task.txt 中写入 "plain task"。
spawn 一个队友 bob（coder），让他先等待任务板，不要在初始 prompt 里直接写文件。
让他空闲后自动扫描任务板，发现任务 3 后自己认领并完成。
```

**预期：**

- bob 通过 idle scan 认领任务 3。
- 任务 3 没有 `[wt:...]` 标记。
- bob 使用普通主目录 handler。
- `run-outputs/s12/plain_task.txt` 出现在主目录。
- 这说明 s12 没有破坏 s11 的普通自治路径。

## 验证 8：边界检查，直接 spawn 不自动换 handler

**Prompt：**

```text
先用 team_status 检查当前队友状态。
如果 bob 或其他队友仍是 idle / working，请先对他们发起 shutdown_request，并等待他们变成 stopped。
确认没有空闲队友还在扫描任务板后，再继续下面的边界测试。

创建任务 4：在绑定 worktree 中写 direct_spawn_boundary.txt，内容为 "boundary"。
创建 worktree "boundary-wt" 并绑定任务 4。
然后 spawn 一个队友 charlie（coder），在初始 prompt 中直接让他写 direct_spawn_boundary.txt。
写完后检查主目录和 boundary-wt worktree 中分别是否存在这个文件。
```

**预期：**

- 这条验证用于观察机制边界，不是失败用例。
- charlie 的初始 prompt 路径默认不会自动替换 worktree-aware handler。
- 如果 charlie 直接使用普通 `write_file`，文件会落在主目录。
- 如果想强制写入 `boundary-wt`，应使用 `worktree_exec`，或让任务 4 走 idle scan 自动认领。
- 如果还有 bob 这类 idle 队友存活，它们可能抢先认领任务 4，导致边界测试被污染。

## 验收结论口径

s12 demo 跑通时，你应该能说清：

- `worktree_create` 建的是独立 git 工作目录，不是普通文件夹。
- `task_list` 里的 `[wt:name]` 是控制面绑定信息。
- `worktree_exec` 是显式隔离执行入口。
- 队友自动隔离只发生在 idle scan 认领绑定任务的路径。
- 普通 s11 自治任务仍然可以在主目录执行。
- s12 没有改 `core/loop.py`，隔离是靠 handler 工厂叠加出来的。
