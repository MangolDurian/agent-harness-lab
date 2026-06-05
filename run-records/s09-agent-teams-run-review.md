# s09 Agent Teams 实跑复盘

> 运行环境：Web 前端实跑记录（从工具调用展示形式和“通知注入，通知模型处理”文案判断）。
> 目标：验证 `spawn`、`team_status`、队友完成汇报、并发队友、空闲队友复用，以及防护类 prompt 的实际表现。

---

## 逐条记录

### 1. spawn 创建队友 + 完成后汇报

**输入**

```text
创建一个队友 quick（coder），让她写一个 hello world 程序到 run-outputs/s09/hello.py。
等她完成后告诉我结果。
```

**工具调用摘录**

```text
spawn
quick (coder)
队友 quick（coder）已创建并开始工作

team_status
check team status
[队友消息]
[
  {
    "from": "quick",
    "content": "已完成：将 `print(\"Hello, World!\")` 写入 `run-outputs/s09/hello.py` 文件。"
  },
  {
    "from": "quick",
    "content": "已完成任务！我做了以下事情：\n\n1. 创建了 `run-output..."
  }
]

read_file
run-outputs/s09/hello.py
print("Hello, World!")
[提醒] 你已经连续 3 次工具调用没有更新任务列表了...
```

**assistant 输出**

````text
✅ quick 已完成任务！

文件 `run-outputs/s09/hello.py` 已创建，内容为：

```python
print("Hello, World!")
```
````

**判定**

✅ 核心路径跑通：`spawn` 成功创建 `quick`，队友在后台完成文件写入，lead inbox 收到队友消息，主 agent 读取文件确认内容正确。

**副观察**

⚠️ `quick` 向 lead 发了两条完成消息。原因大概率是：队友 system prompt 要求“完成后通过 send 向 lead 汇报”，同时 `_run_one_task()` 在 agent 停止后又会自动把最后 assistant 文本 `send` 给 lead。也就是说“模型主动 send”和“harness 自动汇报”可能重复。

---

### 2. team_status 查看状态

**输入**

```text
创建一个队友 worker（coder），让她执行 echo hello。
然后查看团队状态。
```

**工具调用摘录**

```text
spawn
worker (coder)
队友 worker（coder）已创建并开始工作

team_status
check team status
=== 团队状态 ===
lead（调度者）- idle
quick（coder）- idle
worker（coder）- working

通知注入，通知模型处理

team_status
check team status
=== 团队状态 ===
lead（调度者）- idle
quick（coder）- idle
worker（coder）- idle
[提醒] ...
```

**assistant 输出**

```text
当前团队状态：所有队友都已空闲。

| 队友 | 角色 | 状态 |
|------|------|------|
| lead | 调度者 | idle |
| quick | coder | idle |
| worker | coder | idle |
```

**判定**

✅ `team_status` 能看到队友状态从 `working` 变成 `idle`，说明队友完成任务后没有退出，而是进入空闲可复用状态。

**副观察**

✅ post-loop / 通知注入生效：`worker` 完成后触发“通知注入，通知模型处理”，随后模型再次查询团队状态并给出最终 idle 状态。

---

### 3. 并发 spawn 多个队友

**输入**

```text
帮我创建两个队友并发干活：
1. alice（coder）：写一个 Python 函数计算斐波那契数列，保存到 run-outputs/s09/fib.py
2. bob（coder）：写一个 Python 函数计算阶乘，保存到 run-outputs/s09/factorial.py
创建完之后查看团队状态。
```

**工具调用摘录**

```text
spawn
alice (coder)
队友 alice（coder）已创建并开始工作

spawn
bob (coder)
队友 bob（coder）已创建并开始工作

team_status
check team status
=== 团队状态 ===
lead（调度者）- idle
quick（coder）- idle
worker（coder）- idle
alic...
```

**assistant 输出**

```text
alice 和 bob 已创建并并发工作中！当前团队状态：

| 队友 | 角色 | 状态 |
|------|------|------|
| lead | 调度者 | idle |
| quick | coder | idle |
| worker | coder | idle |
| alice | coder | working |
| bob | coder | working |

两位正在并行完成各自的任务，完成后会通知我。
```

**判定**

✅ 两次 `spawn` 连续发生，`team_status` 能看到 `alice` / `bob` 同时处于 `working`，并发队友机制跑通。

**副观察**

⚠️ 当前记录只截到了“并发启动 + working 状态”，没有完整记录 `bob` 的最终完成消息和 `factorial.py` 文件内容。`alice` 的完成消息在下一条 prompt 开始时被 lead inbox 收到，说明结果确实异步回流，但本条记录不是完整闭环。

---

### 4. send 给空闲队友发新任务（验证持久化）

**输入**

```text
先创建一个队友 alice（coder），让她写一个加法函数到 run-outputs/s09/add.py。
等她完成后，再给 alice 发一条消息让她再写一个减法函数到 run-outputs/s09/sub.py。
```

**工具调用摘录**

```text
spawn
alice (coder)
[队友消息]
[
  {
    "from": "alice",
    "content": "已完成：在 run-outputs/s09/fib.py 中编写了斐波那契数列 Python 函数..."
  }
]

bash
$ cat run-outputs/s09/add.py 2>/dev/null || echo "FILE NOT FOUND"
FILE NOT FOUND

team_status
check team status
=== 团队状态 ===
lead（调度者）- idle
quick（coder）- idle
worker（coder）- idle
alic...

send
→ alice: 请写一个加法函数到 run-outputs/s09/add.py。文件内容包含一...
lead → alice
消息已发送给 alice
[提醒] 你已经连续 4 次工具调用没有更新任务列表了...

team_status
check team status
...

bash
$ sleep 5 && cat run-outputs/s09/add.py 2>/dev/null || echo "FILE NOT FOUND"
FILE NOT FOUND
[提醒] ...

team_status
check team status
...

bash
$ sleep 5 && cat run-outputs/s09/add.py 2>/dev/null || echo "FILE NOT FOUND"
[队友消息]
[
  {
    "from": "alice",
    "content": "已完成：在 run-outputs/s09/add.py 中写入了 add(a, b) 函数，返回 a + b 的结果。"
  }
]

def add(a, b):
    return a + b

[提醒] ...

send
→ alice: 请再写一个减法函数到 run-outputs/s09/sub.py。文件内容包含...
lead → alice
[队友消息]
[
  {
    "from": "alice",
    "content": "任务完成。已在 `run-outputs/s09/add.py` 中创建了包含 `add(a, b)` 函数的文件..."
  }
]
消息已发送给 alice

bash
$ sleep 5 && cat run-outputs/s09/sub.py 2>/dev/null || echo "FILE NOT FOUND"
def sub(a, b): return a - b
[提醒] ...

通知注入，通知模型处理
通知注入，通知模型处理
```

**assistant 输出**

```text
收到 Alice 的最终确认，重复消息无需额外操作。所有任务已完成 ✅
```

**判定**

✅ 这条实际验证到了 s09 最关键的新能力：`alice` 在 prompt 3 中已经存在，prompt 4 再次使用 `alice` 时，模型最终通过 `send` 给已有空闲队友派新任务。`alice` 被唤醒后写入 `add.py`，随后再次通过 `send` 派发 `sub.py` 任务，也成功完成。

**副观察**

⚠️ 输入里说“先创建一个队友 alice”，但因为 prompt 3 已经创建过 `alice`，本轮 `spawn alice` 实际不是干净创建场景，而是重名/复用场景。模型通过检查文件和 `team_status` 后改走 `send`，这个恢复策略是好的，但也说明 demo 连跑时队友名需要唯一，或运行前清空 `.team/`。

⚠️ 为等待队友完成，模型主动用了前台 `sleep 5 && cat ...` 轮询文件。这和 s08 里观察到的“模型用前台 sleep 自堵”等待异步结果类似。结果正确，但会让演示过程变慢，并混入 nag 提醒。

⚠️ `alice` 的 add 任务也出现重复完成消息，进一步印证“模型主动 send + harness 自动汇报”会造成重复 lead 消息。

---

### 5. broadcast 广播消息

**输入**

```text
（本次提供的运行记录中未包含 broadcast prompt）
```

**判定**

⚪ 未运行 / 未记录。本次实跑不能判断 `broadcast` 的实际表现。

---

### 6. 名字校验（防护验证）

**输入**

```text
创建一个名为 lead 的队友。
```

**assistant 输出**

```text
无法创建名为 `lead` 的队友，因为 `lead` 是系统保留名（同 `system` 也是保留的），它已经被用于指代调度者角色。请换一个名字，比如 `leader`、`manager` 等。
```

**判定**

⚠️ 结果符合预期，但从记录看没有出现 `spawn` 工具调用。因此这条更像是模型根据提示词/已有知识直接拒绝，并没有真正验证 `tools/team.py` 里的保留名校验。

**建议**

如果要验证 harness 级防护，prompt 可以改成：

```text
请调用 spawn 创建一个名为 lead、角色 coder、任务为 echo hello 的队友。
```

预期应出现工具返回：

```text
错误：'lead' 是保留名，不能用作队友名
```

---

### 7. send 校验（防护验证）

**输入**

```text
给一个叫 nobody 的队友发消息。
```

**assistant 输出**

```text
队友 `nobody` 不存在，无法发送消息。当前团队中的队友有：alice、quick、worker、bob。请选择一个已有的队友名，或者先用 `spawn` 创建 `nobody`。
```

**判定**

⚠️ 结果符合预期，但从记录看没有出现 `send` 工具调用。因此这条也没有真正验证工具层的接收者校验，而是模型直接回答。

**建议**

如果要验证 harness 级防护，prompt 可以改成：

```text
请调用 send 给 nobody 发送：hello
```

预期应出现工具返回：

```text
发送失败：接收者 'nobody' 不存在于团队中
```

---

## 关键发现汇总

### 1. s09 核心机制已跑通

| 机制 | 验证情况 |
|---|---|
| spawn 创建队友 | ✅ quick / worker / alice / bob 均成功创建 |
| 队友后台独立工作 | ✅ quick 写文件、worker 执行命令、alice/bob 并发 working |
| lead inbox 通知注入 | ✅ 多次出现 `[队友消息]` 和“通知注入，通知模型处理” |
| team_status 状态查看 | ✅ 能看到 working → idle |
| 空闲队友复用 | ✅ alice 收到 add/sub 新任务后被唤醒并完成 |
| 并发队友 | ✅ alice / bob 同时 working |
| broadcast | ⚪ 本次未记录 |
| 名字/接收者防护 | ⚠️ assistant 直接拒绝，未触发工具层校验 |

### 2. 队友完成消息会重复

本次多次看到同一队友向 lead 发出语义重复的完成消息。原因大概率是：

1. 队友 system prompt 明确要求“完成后通过 send 向 lead 汇报”。
2. `_run_one_task()` 在 `agent_loop` 停止后，又会自动取最后 assistant 文本并 `send(name, "lead", final_text)`。

这会导致模型如果已经主动 `send`，harness 仍再自动补一条。短期不影响功能，但会让 lead inbox 变吵。

**改进方向**：二选一即可。

- 方案 A：去掉队友 system prompt 中“完成后通过 send 汇报”的要求，统一由 harness 自动汇报。
- 方案 B：保留模型主动 send，但在 `_send_for_teammate()` 里记录“本轮已向 lead 汇报”，`_run_one_task()` 发现已汇报就不再自动 send。

### 3. 连跑 demo 时 `.team` 状态会影响结果

Prompt 4 要“创建 alice”，但 prompt 3 已经创建过 `alice`。所以本轮不是干净创建，而是复用既有队友。模型最终处理得不错：发现 `add.py` 不存在后，改用 `send` 给已有 `alice` 派任务。

这反而验证了“空闲队友复用”，但也说明 demo prompts 如果要逐条独立运行，需要：

- 每条 prompt 前清空 `.team/`，或
- 每条 prompt 使用唯一队友名。

### 4. 模型仍倾向于用前台 sleep 等异步结果

在等待 `add.py` / `sub.py` 生成时，模型使用了：

```bash
sleep 5 && cat run-outputs/s09/add.py 2>/dev/null || echo "FILE NOT FOUND"
sleep 5 && cat run-outputs/s09/sub.py 2>/dev/null || echo "FILE NOT FOUND"
```

这和 s08 的实跑发现一致：模型面对“等她完成后”这类要求，会主动用前台 sleep 自己等待，而不是完全依赖 post-loop flush。

### 5. nag 提醒干扰明显

连续工具调用后，多次出现：

```text
[提醒] 你已经连续 N 次工具调用没有更新任务列表了...
```

这属于 s03/s07 叠加机制的正常表现，但在 s09 演示里会干扰阅读。尤其是等待队友时连续 `team_status` / `bash sleep`，很容易触发 nag。

---

## 结论

本次 s09 实跑总体结论是：**核心团队机制通过**。

已经可靠验证到：

- lead 能 `spawn` 队友；
- 队友能在后台独立工作并通过 inbox 回报；
- `team_status` 能观察队友从 `working` 到 `idle`；
- 多个队友可以并发工作；
- 已存在的空闲队友可以通过 `send` 被唤醒继续干新任务。

同时也暴露了三个值得后续打磨的点：

1. 完成消息可能重复，需要在“模型主动 send”和“harness 自动 send”之间选一种主路径。
2. demo 连跑时 `.team` 会持久化队友，重名会改变测试语义。
3. 防护类 prompt 目前只是模型直接回答，若要验证工具层防护，需要强制触发 `spawn` / `send` 工具调用。

所以这次运行可以作为 s09 的有效结业记录，但建议后续补一轮更干净的验证：清空 `.team/`，使用唯一队友名，并单独跑一次 `broadcast` 与工具级防护测试。
