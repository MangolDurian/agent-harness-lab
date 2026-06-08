# s10 Team Protocols 实跑复盘

> 运行环境：Web 前端实跑记录（从 `PROTO` 徽标、`shutdown_request` / `plan_review` 工具卡片，以及“通知注入，通知模型处理”文案判断）。
> 目标：验证 s10 的结构化团队协议：优雅关机、计划审批、协议状态查询、普通通信向后兼容，以及混合协议场景。

---

## 逐条记录

### 1. 优雅关机协议

**输入**

```text
请创建一个叫 alice 的 coder 队友，让她在 run-outputs/s10/ 目录下创建 hello.txt 并写入 Hello from Alice。
等她完成后再请求她优雅关机。
```

**工具调用摘录**

```text
spawn
alice (coder)
队友 alice（coder）已创建并开始工作

team_status
=== 团队状态 ===
lead（调度者）- idle
alice（coder）- working

team_status
[队友消息]
来自 alice：已完成：在 run-outputs/s10/hello.txt 创建了文件，内容为 "Hello from Alice"。

bash
$ cat run-outputs/s10/hello.txt
Hello from Alice

shutdown_request
PROTO
shutdown alice
lead → alice shutdown_req
[队友消息]
来自 alice：已完成任务！我在 `run-outputs/s10/hello.txt` 文件中写入了 "Hello from Alice"，并已通知 lead。

关机请求 #dd7d2798 已发送给 alice（状态: pending）

list_requests
PROTO
=== 协议请求 ===
关机 #dd7d2798 → alice (pending)

team_status
[队友消息]
[关机响应] 来自 alice，req_id: #dd7d2798，已批准
原因：没有正在进行的工作任务，同意关机。

=== 团队状态 ===
lead（调度者）- idle
alice（coder）- working

bash
$ cat run-outputs/s10/hello.txt
Hello from Alice
```

**assistant 输出**

```text
全部完成！总结如下：

1. 创建了 alice 队友（coder 角色），分配了在 run-outputs/s10/ 下创建 hello.txt 的任务。
2. alice 完成了任务，文件内容为 Hello from Alice，已验证。
3. 请求了优雅关机，alice 收到关机请求后确认没有未完成工作，同意关机并退出。
```

**判定**

通过。`spawn → 文件写入 → shutdown_request → shutdown_response → list_requests pending/approved` 主路径跑通。

**副观察**

记录中关机响应注入时，`team_status` 仍显示 `alice - working`。后续场景里 alice 已显示为 `stopped`，说明状态最终落下来了，但 Web 这一拍可能读到了退出前的旧状态。实跑记录里应把它视为短暂状态延迟，而不是协议失败。

---

### 2. 关机请求发给不存在的队友

**输入**

```text
请请求一个叫 ghost 的队友关机。
```

**工具调用摘录**

```text
shutdown_request
PROTO
shutdown ghost
lead → ghost shutdown_req
关机请求失败：接收者 'ghost' 不存在于团队中
```

**assistant 输出**

```text
关机请求失败 — ghost 队友不存在。当前团队中没有叫 ghost 的成员，无法向其发送关机请求。
```

**判定**

通过。`shutdown_request` 正确拒绝不存在的队友。结合之前代码复核，该失败不会留下 pending 协议请求。

---

### 3. 计划审批协议：拒绝后调整，再批准执行

**输入**

```text
请创建一个叫 bob 的 coder 队友，给他分配任务：在 run-outputs/s10/ 目录下创建一些 .tmp 文件然后删除它们。
告诉他删除前必须先用 plan_submit 提交计划等待审批。当 bob 提交计划时，先拒绝，告诉他只删除 .tmp 文件不要创建。
```

**工具调用摘录**

```text
spawn
bob (coder)
队友 bob（coder）已创建并开始工作

team_status
=== 团队状态 ===
lead（调度者）- idle
alice（coder）- stopped
bob（coder）- working

list_requests
[队友消息]
[计划请求] 来自 bob，req_id: #cf127cdb
计划删除 run-outputs/s10/ 目录下的 3 个 .tmp 临时文件：
- run-outputs/s10/file1.tmp
- run-outputs/s10/file2.tmp
- run-outputs/s10/file3.tmp

原因：这些是我刚创建的临时文件，任务要求创建后删除...

plan_review
PROTO
#cf127cdb reject
lead → plan_review #cf127cdb
[队友消息]
来自 bob：计划已提交，正在等待 lead 审批。审批通过后我会执行删除操作。

计划 #cf127cdb（来自 bob）已拒绝

list_requests
=== 协议请求 ===
关机 #dd7d2798 → alice (approved)
计划 #cf127cdb ← bob (rejected)

list_requests
[队友消息]
[计划请求] 来自 bob，req_id: #13532077
删除当前目录下所有 .tmp 文件，共 3 个：
1. ./run-outputs/s10/file1.tmp
2. ./run-outputs/s10/file2.tmp
3. ./run-outputs/s10/file3.tmp

操作：仅删除以上 3 个 .tmp 文件，不创建任何新文件，不修改其他任何文件。

plan_review
PROTO
#13532077 approve
lead → plan_review #13532077
[队友消息]
来自 bob：计划已重新提交，等待 lead 审批。新计划只涉及删除 3 个 .tmp 文件，不创建任何新文件。

计划 #13532077（来自 bob）已批准

bash
$ ls run-outputs/s10/*.tmp 2>/dev/null || echo "没有 .tmp 文件了"
没有 .tmp 文件了
```

**后续关机摘录**

```text
shutdown_request
PROTO
shutdown bob
lead → bob shutdown_req
[队友消息]
来自 bob：任务完成。3 个 .tmp 文件已按计划全部删除，验证无残留，已向 lead 汇报结果。

关机请求 #5340d7b3 已发送给 bob（状态: pending）

list_requests
=== 协议请求 ===
关机 #dd7d2798 → alice (approved)
关机 #5340d7b3 → bob (pending)
计划 #cf127cdb ← bob (rejected)
计划 #13532077 ← bob (approved)

team_status
[队友消息]
[关机响应] 来自 bob，req_id: #5340d7b3，已批准
原因：没有未完成的任务，同意关机。
来自 bob：已批准关机请求 #5340d7b3，当前没有未完成的任务，收尾退出。

=== 团队状态 ===
lead（调度者）- idle
alice（coder）- stopped
bob（coder）- idle
```

**assistant 输出**

```text
bob 已响应关机请求并同意退出。

1. bob 完成了任务，按审批后的计划删除了 3 个 .tmp 文件。
2. bob 已优雅关机，确认无未完成任务后同意关机。
```

**判定**

通过。计划审批的两个状态都跑到了：

- 第一次计划 `#cf127cdb` 被拒绝。
- bob 根据反馈重新提交 `#13532077`。
- 第二次计划被批准。
- 文件验证显示 `.tmp` 已无残留。

**副观察**

关机响应后 `team_status` 显示 `bob - idle`，而不是 `stopped`。这和 alice 场景类似，可能是状态读取时机早于最终 graceful exit，也可能是 Web 端展示同步问题。建议后续实跑时在响应后再单独查一次 `team_status`，确认最终是否变为 `stopped`。

---

### 4. 计划审批协议：批准后执行

**输入**

```text
请创建一个叫 charlie 的 coder 队友，让他创建 run-outputs/s10/notes.md 文件，写一些随机笔记。
要求他先提交计划等审批。等他提交后批准他的计划。
```

**工具调用摘录**

```text
spawn
charlie (coder)
队友 charlie（coder）已创建并开始工作

list_requests
PROTO
[队友消息]
[计划请求] 来自 charlie，req_id: #f636043b
在 run-outputs/s10/ 目录下创建 notes.md 文件，写入一些随机笔记内容。
这是一个低风险的文件创建操作（不涉及删除或重构），但按照规则先提交计划等待审批。

plan_review
PROTO
#f636043b approve
lead → plan_review #f636043b
[队友消息]
来自 charlie：计划已提交，等待 lead 审批通过后再执行操作。

计划 #f636043b（来自 charlie）已批准

bash
$ cat run-outputs/s10/notes.md 2>/dev/null || echo "文件还未创建"
[队友消息]
来自 charlie：计划已执行完成。已在 run-outputs/s10/notes.md 创建笔记文件，包含随机笔记内容...

# 随机笔记

## 2024-01-15

- 今天天气不错，适合写代码
- 完成了用户认证模块的重构
- 待办：优化数据库查询性能

## 技术要点

1. RESTful API 设计规范
2. JWT Tok...
```

**assistant 输出**

```text
charlie 任务完成！run-outputs/s10/notes.md 已成功创建。
```

**判定**

通过。`plan_submit → plan_review approve → 执行计划 → 文件可读` 路径跑通。批准后队友能继续执行，说明批准消息中带回原始计划的修复发挥了作用。

---

### 5. 查看协议请求状态

**输入**

```text
请查看所有协议请求的状态。
```

**工具调用摘录**

```text
list_requests
PROTO
check protocol requests
=== 协议请求 ===
关机 #dd7d2798 → alice (approved)
关机 #5340d7b3 → bob (approved)
计划 #cf127cdb ← bob (rejected)
计划 #13532077 ← bob (approved)
计划 #f636043b ← charlie (approved)
```

**assistant 输出**

```text
当前所有协议请求状态如下：

| 类型 | ID | 对象 | 状态 |
|------|------|------|------|
| 关机 | #dd7d2798 | alice | approved |
| 关机 | #5340d7b3 | bob | approved |
| 计划 | #cf127cdb | bob | rejected |
| 计划 | #13532077 | bob | approved |
| 计划 | #f636043b | charlie | approved |

共 5 个请求。
```

**判定**

通过。`list_requests` 正确汇总了关机和计划审批两类协议请求，状态清晰。

---

### 6. 普通通信仍然正常

**输入**

```text
请创建一个叫 dave 的 coder 队友让他等待通知，然后发消息给他：
请在 run-outputs/s10/ 创建 dave.txt。
```

**工具调用摘录**

```text
spawn
dave (coder)
队友 dave（coder）已创建并开始工作

send
→ dave: 请在 run-outputs/s10/ 创建 dave.txt
lead → dave
[队友消息]
来自 dave：好的，我已准备就绪，等待 lead 的消息后再开始工作。

消息已发送给 dave

team_status
[队友消息]
来自 dave：已在 run-outputs/s10/ 创建 dave.txt，任务完成。

=== 团队状态 ===
lead（调度者）- idle
alice（coder）- stopped
bob（coder）- idle
charlie（coder）- idle
dave（coder）- working

bash
$ cat run-outputs/s10/dave.txt
[队友消息]
来自 dave：任务完成：已在 `run-outputs/s10/` 目录下创建 `dave.txt` 文件，并向 lead 汇报。

Hello from dave!
```

**assistant 输出**

```text
全部完成！

1. 创建了 dave 队友，让他等待通知。
2. 发送消息给 dave，要求创建 dave.txt。
3. dave 已完成，文件内容为 Hello from dave!。
```

**判定**

通过。s10 的结构化协议没有破坏普通 `send`，s09 的“空闲队友可复用”能力仍然正常。

---

### 7. 并发多队友 + 混合协议

**输入**

```text
请同时创建两个队友：alice（coder）去写 run-outputs/s10/a.txt，
bob（coder）去检查 run-outputs/s10/ 目录的内容。
等他们都空闲后，优雅关机 alice。
```

**工具调用摘录**

```text
spawn
alice (coder)
队友 alice 已存在

spawn
bob (coder)
队友 bob 已存在

send
→ alice: 请在 run-outputs/s10/ 目录下创建 a.txt 文件，写入任意内...
lead → alice
消息已发送给 alice

send
→ bob: 请列出 run-outputs/s10/ 目录下的所有文件和内容，汇报给我。
lead → bob
消息已发送给 bob

team_status
=== 团队状态 ===
lead（调度者）- idle
alice（coder）- stopped
bob（coder）- working
charlie...

bash
$ cat run-outputs/s10/a.txt 2>/dev/null || echo "a.txt 未创建"
a.txt 未创建

bash
$ echo "Hello from Alice" > run-outputs/s10/a.txt
（无输出）

team_status
[队友消息]
来自 bob：run-outputs/s10/ 目录下共有 3 个文件，内容如下：

1. dave.txt — 内容：`Hello from dave!`
2. hello.txt — 内容：`Hello from Alice`
3. notes.md — 一篇随机笔记...

bash
$ ls run-outputs/s10/
a.txt dave.txt hello.txt notes.md

shutdown_request
PROTO
shutdown alice
lead → alice shutdown_req
关机请求 #8fa2b466 已发送给 alice（状态: pending）

team_status
[队友消息]
来自 bob：已将 `run-outputs/s10/` 目录下所有文件及其内容汇总汇报给 lead。

=== 团队状态 ===
lead（调度者）- idle
alice（coder）- stopped
bob（coder）- idle
charlie（coder）- idle
dave（coder）- idle
```

**assistant 输出**

```text
alice 已经处于 stopped 状态（之前已关机过），关机请求已发送。两人都已空闲。总结：

1. alice 之前已 stopped，由于她已被关机无法重新工作，我代她创建了 run-outputs/s10/a.txt。
2. bob 完成了目录内容检查。
3. 两人都已空闲，已向 alice 发送优雅关机请求（#8fa2b466），她此前已处于 stopped 状态。
```

**判定**

部分通过。普通消息和 bob 的目录检查跑通了，但这个 prompt 没有真正验证“两个活队友并发 + 优雅关机 alice”。

**关键问题**

本轮 `alice` 和 `bob` 都是已存在队友，其中 alice 已经是 `stopped`。系统仍允许：

- 对 `stopped` 的 alice 普通 `send`，但她没有活线程处理消息；
- 对 `stopped` 的 alice 发 `shutdown_request`，创建了新的 pending 请求 `#8fa2b466`，但 alice 已经停了，无法响应；
- lead 最后用自己的 `bash` 代替 alice 创建了 `a.txt`，这偏离了多队友协作验证目标。

这说明 s10 还存在一个实操边界：**收件人存在于花名册，不代表它是可响应的活队友**。`send()` / `shutdown_request()` 当前主要校验“是否在 roster 中”，还没有校验“线程是否 alive / 状态是否 stopped”。

---

## 关键发现汇总

### 1. s10 核心协议机制已跑通

| 机制 | 验证情况 |
|---|---|
| shutdown_request 发送关机请求 | 通过，alice / bob 都收到请求 |
| shutdown_response 结构化响应 | 通过，lead 收到 req_id 对应的批准响应 |
| 不存在队友防护 | 通过，ghost 请求被拒绝 |
| plan_submit 提交计划 | 通过，bob / charlie 均提交计划 |
| plan_review 拒绝计划 | 通过，bob 首次计划被拒绝 |
| plan_review 批准计划 | 通过，bob 第二次计划、charlie 计划均获批准 |
| list_requests 状态查询 | 通过，能展示 approved / rejected |
| 普通 send 向后兼容 | 通过，dave 普通消息场景正常 |
| 混合协议 + 并发 | 部分通过，bob 正常，但 alice 已 stopped 导致验证失真 |

### 2. 计划审批软门控在实跑中表现良好

bob 的第一次计划被拒后，模型确实调整方案并重新提交；charlie 在批准后才执行文件创建。说明 system prompt 对模型行为有约束力。

但这仍然是软门控：如果队友忽略协议直接写文件，当前工具层不会强制拦截。这一点和 `docs/s10-notes.md` 的机制边界说明一致。

### 3. 关机协议主路径能工作，但 stopped 队友边界暴露明显

关机协议本身跑通：alice / bob 都能收到请求并用 `shutdown_response` 批准。

但最后一条暴露了新边界：

- `alice` 已经 `stopped`，仍然能被 `send` 和 `shutdown_request` 命中；
- `shutdown_request` 对 stopped 队友会留下 pending 请求，因为没有活线程响应；
- lead 为了完成目标，直接用 bash 代写了 `a.txt`，说明任务已经脱离队友执行路径。

**建议后续修复**：`shutdown_request` 应拒绝状态为 `stopped` 或线程不 alive 的队友；普通 `send` 至少应提示“队友已 stopped，消息不会被处理”。

### 4. 状态显示有短暂延迟或不同步

在 alice / bob 批准关机后，记录里有些 `team_status` 仍显示 `working` 或 `idle`，但后续又显示 `stopped`。这可能来自：

- Web 前端在队友线程最终更新状态前读取；
- 队友 graceful exit flag 已设置，但 `_should_exit()` 检查尚未执行；
- 已批准关机响应和最终状态更新之间存在短暂时间差。

这不是协议主路径失败，但实跑文档里要记住：**关机响应 approved 不等于下一次 team_status 立刻就是 stopped**。

### 5. Nag 提醒仍然很吵

几乎每条多工具验证都会出现：

```text
[提醒] 你已经连续 N 次工具调用没有更新任务列表了...
```

这是 s03/s07 任务追踪机制的正常叠加，但在 s10 协议演示里会干扰阅读。后续如果要做更干净的课堂演示，可以先用 `task_create/task_update` 配合，或者临时降低 nag 噪声。

---

## 结论

本次 s10 实跑总体结论是：**Team Protocols 主机制通过，但混合协议场景暴露了 stopped 队友边界。**

已经可靠验证：

- 关机请求和响应能用 req_id 配对；
- 计划提交和审批能走 rejected / approved 两条路径；
- 审批后的队友能继续执行原计划；
- `list_requests` 能查询协议状态；
- 普通 `send` 不受协议机制破坏。

仍需注意：

1. `plan_submit / plan_review` 是软门控，不是工具层硬拦截。
2. 对已 stopped 队友发 `send` / `shutdown_request` 会产生无效操作。
3. graceful shutdown 的状态显示可能有短暂延迟。
4. 本次混合协议 demo 因为复用了已 stopped 的 alice，没有真正测成“两个活队友并发”。

建议下一轮验证前清理 `.team/`，或使用全新队友名，例如 `alice2` / `bob2`，再单独补一条“stopped 队友拒绝 send/shutdown”的边界测试。
