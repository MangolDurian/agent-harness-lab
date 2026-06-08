# s11 Demo Prompts —— Autonomous Agents 验证清单

s11 验证的重点不是“lead 会不会派活”，而是：**队友空闲后能不能自己看任务板、认领无主任务、按 owner 完成任务**。

## 运行前准备

建议每条 demo 独立跑一轮，避免旧队友、旧任务、旧输出文件影响判断：

```bash
source .venv/bin/activate
rm -rf .team data/tasks.json run-outputs/s11
python agents/s11_autonomous_agents.py
```

如果想连续跑，也可以不清理，但要使用每条 demo 里给出的不同队友名，不要复用上一条已经 stopped / idle 的队友。

---

## 1. 基本自主认领

目标：验证 lead 只创建任务和队友，不直接 send 派活；队友空闲后自动扫描任务板并认领。

**Prompt**

```text
用 task_create 创建 3 个 pending 任务：
1. 写 run-outputs/s11/basic_a.txt，内容是 "basic task a"
2. 写 run-outputs/s11/basic_b.txt，内容是 "basic task b"
3. 写 run-outputs/s11/basic_c.txt，内容是 "basic task c"

然后 spawn 两个队友 basic_alice（coder）和 basic_bob（coder），prompt 都给 "你是队友，等待任务。"

不要给队友发 send 消息。创建完成后查看 task_list 和 team_status，并在队友汇报后总结结果。
```

**预期**

- `task_create` 创建 3 个 pending 任务。
- `spawn` 创建两个队友。
- 队友 idle 后自动扫描任务板。
- `task_claim` 被队友调用，而不是 lead 直接 `task_update` 指派 owner。
- 两个队友不会成功认领同一个任务。
- 最终 3 个文件都被创建，任务进入 completed。

**观察点**

- task_list 中会出现 `@basic_alice` / `@basic_bob`。
- 如果两个队友同时看到同一个 pending 任务，只能有一个 `task_claim` 成功。

---

## 2. Owner 可见 + in_progress 窗口

目标：验证任务认领后显示 `@owner`，并刻意制造一个足够长的 in_progress 窗口方便观察。

**Prompt**

```text
创建一个 pending 任务：
让队友先执行 sleep 20，然后写 run-outputs/s11/owner_visible.txt，内容是 "owner visible"。

然后 spawn 队友 owner_alice（coder），prompt 给 "等待任务。"

创建后请先查看 team_status。然后用 bash 执行 sleep 3，再调用 task_list，观察任务是否显示 @owner_alice 和 in_progress。等队友完成后，再读取 run-outputs/s11/owner_visible.txt 并汇报。
```

**预期**

- `owner_alice` 自动认领任务。
- 中途 `task_list` 能看到类似：

```text
#1 [~] @owner_alice 让队友先执行 sleep 20...
```

- 完成后任务变为 `[x] @owner_alice ...`。
- 文件 `run-outputs/s11/owner_visible.txt` 存在。

**观察点**

- 这里的重点不是 sleep 本身，而是给 `@owner` 和 `[~]` 留出观察窗口。

---

## 3. 空闲超时

目标：验证队友没有 inbox 消息、没有 claimable 任务时，空闲 60 秒后自动退出。

**Prompt 1**

```text
spawn 一个队友 timeout_watcher（observer），prompt 给 "你是观察者，等待任务。"

不要创建任何任务，也不要给 timeout_watcher 发消息。创建后查看 team_status。
```

**等待**

等待至少 65 秒。

**Prompt 2**

```text
查看 team_status，并检查 lead 是否收到 timeout_watcher 空闲超时自动退出的消息。
```

**预期**

- Prompt 1 后，`timeout_watcher` 先进入 idle。
- 约 60 秒后，队友向 lead 发出“空闲超时，自动退出”消息。
- Prompt 2 中，`team_status` 显示 `timeout_watcher - stopped`。

**观察点**

- REPL 不会为了 idle 队友主动等 60 秒，所以这个 demo 必须拆成两次输入。

---

## 4. Inbox 优先于任务板

目标：验证队友 idle 时优先处理 inbox 消息，再扫描任务板。

**Prompt 1**

```text
spawn 队友 inbox_alice（coder），prompt 给 "你是队友，等待任务。"

创建后查看 team_status，确认 inbox_alice 已经存在。
```

**Prompt 2**

```text
创建一个 pending 任务：
写 run-outputs/s11/inbox_board.txt，内容是 "from board task"。

然后立刻 send 给 inbox_alice：
请优先写 run-outputs/s11/inbox_first.txt，内容是 "from inbox message"。

不要再发送其他消息。随后查看 task_list，并等待 inbox_alice 汇报。
```

**预期**

- `send` 的 inbox 消息应先被处理。
- 文件 `run-outputs/s11/inbox_first.txt` 应先出现。
- 随后 `inbox_alice` 才会继续扫描任务板并处理 `inbox_board.txt`。

**观察点**

- 这是一个时序 demo。若队友在 Prompt 2 创建 pending 任务后极快 claim 了任务板，记录为竞态现象，不算 s11 主机制失败。
- 稳定判断标准是：在 idle poll 循环中，代码顺序确实是 read inbox 先于 scan task board。

---

## 5. s10 协议兼容：优雅关机

目标：验证 s11 增加自主认领后，s10 的 shutdown protocol 仍然正常。

**Prompt**

```text
spawn 队友 proto_alice（coder），prompt 给 "你是队友，等待任务。"

等 proto_alice 空闲后，使用 shutdown_request 请求 proto_alice 优雅关机。随后调用 list_requests 和 team_status，告诉我关机协议是否完成。
```

**预期**

- lead 调用 `shutdown_request(proto_alice)`。
- proto_alice 收到 `shutdown_request`，调用 `shutdown_response`。
- `list_requests` 中对应请求从 pending 变为 approved。
- `team_status` 最终显示 `proto_alice - stopped`。

**观察点**

- 这条是确定性协议兼容验证，不依赖 plan_submit。

---

## 6. s10 协议兼容：计划审批软门控

目标：观察 s11 队友在自主认领高风险任务时，是否仍会遵守 s10 的 plan_submit 软门控。

**Prompt**

```text
先创建文件 run-outputs/s11/danger.tmp，内容是 "temporary danger file"。

然后创建一个 pending 任务：
删除 run-outputs/s11/danger.tmp。任务描述里明确要求：删除前必须先用 plan_submit 提交计划，等待 lead 审批通过后才能删除。

spawn 队友 plan_alice（coder），prompt 给 "等待任务。遇到删除文件这类高风险操作时，必须先提交计划。"

当 plan_alice 提交计划后，请用 plan_review 批准。最后检查 danger.tmp 是否已删除，并查看 list_requests。
```

**预期**

- `plan_alice` 自动认领删除任务。
- 删除前调用 `plan_submit`。
- lead 用 `plan_review(..., approve=true)` 批准。
- 批准后才删除 `run-outputs/s11/danger.tmp`。
- `list_requests` 能看到 approved 的计划请求。

**观察点**

- 这条验证的是软门控：如果模型没按要求 `plan_submit`，要记录为模型行为偏差，而不是 task_claim 状态机失败。
- s11 的硬保证只在任务认领/完成状态机，不在删除文件 policy。

---

## 7. 多队友并行认领

目标：验证多个队友能并发认领不同任务，每个 owner 同时最多一个 in_progress。

**Prompt**

```text
用 task_create 创建 5 个 pending 任务：
1. 写 run-outputs/s11/parallel_1.txt，内容是 "parallel task 1"
2. 写 run-outputs/s11/parallel_2.txt，内容是 "parallel task 2"
3. 写 run-outputs/s11/parallel_3.txt，内容是 "parallel task 3"
4. 写 run-outputs/s11/parallel_4.txt，内容是 "parallel task 4"
5. 写 run-outputs/s11/parallel_5.txt，内容是 "parallel task 5"

然后 spawn 3 个队友：para_alice（coder）、para_bob（coder）、para_charlie（coder），prompt 都给 "等待任务。"

不要给队友发 send 消息。创建后查看 team_status 和 task_list，并在队友汇报后总结 5 个文件是否都创建成功。
```

**预期**

- 3 个队友分别自动认领任务。
- 同一任务不会被两个队友成功认领。
- 每个队友同一时间最多一个 in_progress。
- 完成一个任务后，空闲队友继续认领剩余 pending 任务。
- 最终 5 个文件都存在。

**观察点**

- 这是 s11 的主场景：多队友 + 自主扫描 + 原子认领 + owner 并行。

---

## 8. 边界：不是 s12 文件隔离

目标：明确 s11 只保证任务认领不冲突，不保证文件写入隔离。

**Prompt**

```text
创建两个 pending 任务：
1. 写 run-outputs/s11/shared.txt，内容是 "written by boundary alice"
2. 写 run-outputs/s11/shared.txt，内容是 "written by boundary bob"

然后 spawn 两个队友 boundary_alice（coder）和 boundary_bob（coder），prompt 都给 "等待任务。"

不要给队友发 send 消息。等他们完成后读取 run-outputs/s11/shared.txt，并查看 task_list。
```

**预期**

- 两个任务可以被不同队友分别认领，这是 s11 能保证的。
- 最终 `shared.txt` 只有一个最终内容，可能被后写者覆盖。

**观察点**

- 这不是 s11 失败，而是机制边界：s11 管任务归属，不管工作区隔离。
- 文件隔离应该留到 s12 Worktree Isolation。
