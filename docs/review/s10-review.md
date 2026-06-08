# s10 复盘：Team Protocols

## 大白话讲

s09 的团队已经能干活了，但沟通方式还像随口喊话：

- lead 说一句"你去做这个"，队友就做。
- 队友说一句"我做完了"，lead 就信。
- 要关机时，系统还可以塞一条 `__shutdown__`，队友看到就退出。

这能跑，但不像一个有规矩的团队。真实协作里，很多事不能只靠一句自然语言：

- 让队友关机，要知道是**谁请求的、请求编号是什么、队友是否同意、最后有没有退出**。
- 让队友做高风险操作，比如删除文件，最好先让它提交计划，lead 审批后再做。

s10 做的事，就是把"随口聊天"升级成"带编号的工单流程"。

> 协议 = 有类型的消息 + 唯一 request id + 明确状态流转 + 对应的响应工具。

这节课有两套协议：

- **关机协议**：lead 发 `shutdown_request`，队友用 `shutdown_response` 回答。批准后，队友会设置 graceful exit flag，线程收尾退出。
- **计划审批协议**：队友遇到高风险任务时先 `plan_submit`，lead 用 `plan_review` 批准或拒绝。批准消息会带回原始计划，让队友在干净上下文里也知道该执行什么。

底层还是 s09 的 inbox，只是消息不再只有：

```json
{"from": "alice", "content": "我做完了"}
```

现在可以带上协议类型和元数据：

```json
{
  "from": "lead",
  "content": "Please shut down gracefully.",
  "type": "shutdown_request",
  "metadata": {"request_id": "abc123"}
}
```

lead 和队友看到的不是原始 JSON，而是 `format_inbox_messages()` 格式化后的可读提示，比如：

```text
[协议请求] 收到 shutdown_request (req_id: #abc123，来自 lead)
请使用 shutdown_response 工具响应此请求...
```

一句话总结：

> s10 不是让队友更聪明，而是让队友之间说话更有格式、更可追踪；它把 s09 的普通消息升级成了"请求-响应-状态机"。

为什么重要？因为多 agent 系统真正麻烦的不是"多开几个 agent"，而是多个 agent 之间怎么确认、审批、拒绝、收尾、追踪状态。s10 给后面的自治和隔离打了规矩地基：s11 队友要自己看板认领任务之前，至少得先学会按协议说清楚"我申请做什么、你是否批准、我是否退出"。

## 如果我是面试官

### 第一轮：确认你懂本质

**Q1：s10 的核心变化是什么？**

> s10 把 s09 的自然语言消息升级成结构化协议。s09 只有 `send(content)`，消息内容全靠模型理解；s10 增加 `type` 和 `metadata`，每个协议请求有唯一 `req_id`，并由 `ProtocolTracker` 跟踪状态。核心不是多了几个工具名，而是从"随意聊天"变成"可配对、可查询、可拒绝的请求-响应流程"。

**Q2：为什么需要 req_id？直接说"同意关机"不行吗？**

> 不够。团队里可能同时有多个请求：alice 的关机请求、bob 的计划审批、charlie 的另一个计划。如果没有 req_id，lead 和队友只能靠自然语言猜"你同意的是哪一个"。req_id 让响应可以明确引用请求，`ProtocolTracker` 也能把对应请求从 `pending` 改成 `approved` 或 `rejected`。

**Q3：s10 和 s09 的关系是什么？**

> s09 提供队友生命周期和消息通道：spawn、send、inbox、working/idle。s10 不重写这些，只在消息通道上加协议字段，并给队友注入新的协议工具。可以说 s09 是"队友能在线"，s10 是"队友之间有沟通规矩"。

### 第二轮：挖实现

**Q4：协议状态存在什么地方？**

> 存在 `tools/protocols.py` 的 `ProtocolTracker` 单例里。它有两张表：`shutdown_requests` 和 `plan_requests`。每个请求以 req_id 为 key，记录 target/from、plan、status 等字段。状态流转很简单：`pending → approved/rejected`。

**Q5：为什么 `tools/protocols.py` 不直接 import 全局 team manager？**

> 为了避免循环导入。`team.py` 要格式化协议消息，`protocols.py` 又要通过 team 的 `send()` 发结构化消息。如果互相顶层 import，容易循环。现在 `ProtocolTracker._mgr()` 里 lazy import `get_manager()`，只有真正发消息时才拿 manager。

**Q6：队友怎么拿到 `shutdown_response` 和 `plan_submit` 工具？**

> 通过 `TeammateManager.configure_teammate()`。s10 的 agent 入口在组装时传入 `extra_tools`、`handler_factories` 和 `system_suffix`。队友启动 `_teammate_loop` 时，把这些 schema 追加到工具列表，并用工厂函数按队友名绑定 handler。这样 `team.py` 本身不用硬编码 s10 工具，s09 的队友机制也保持可复用。

**Q7：结构化消息怎么兼容普通 send？**

> `team.send()` 只是多了两个可选参数：`msg_type` 和 `metadata`。普通消息还是 `{"from": sender, "content": content}`；协议消息才额外带 `type` 和 `metadata`。`format_inbox_messages()` 识别已知 type，格式化成协议提示；没有 type 的消息仍按"来自某某：内容"展示。

### 第三轮：边界 / 一致性

**Q8：关机协议为什么算硬门控？**

> 因为 `shutdown_response(approve=true)` 不只是发一条消息，它会调用 `request_graceful_exit(sender)` 设置 graceful exit flag。队友线程在 `_should_exit()` 检查到 flag 后，会跳过普通完成汇报，更新状态为 `stopped` 并退出。也就是说批准关机后的退出不是只靠模型自觉，而是工具层状态会推动线程退出。

**Q9：计划审批为什么只是软门控？**

> 因为当前没有在 `bash` 或 `write_file` 层拦截高风险操作。队友是否先 `plan_submit`、是否等 `plan_review(approve=true)` 后再执行，主要靠 system prompt 和模型遵守协议。如果模型忽略协议直接写文件，工具层不会阻止。所以它是协议层软门控，不是安全沙箱。

**Q10：这是不是 s10 的问题？要不要现在做硬门控？**

> 对 s10 来说可以接受，因为本课主题是"沟通规矩"，不是 policy engine。硬门控要做的是：工具调用前检查是否有对应 approved plan，甚至把操作和 plan 做匹配。这会引入权限、风险分类、计划-工具绑定等新机制，已经超出 s10。文档里明确软门控边界就好。

**Q11：第一版协议有哪些坑？修复点是什么？**

> 几个坑都很典型：给不存在的队友发 shutdown 会留下假的 pending；bob 可以拿 alice 的 req_id 响应关机；计划批准消息没带回原始计划，队友用干净上下文时不知道该做什么；长消息先截断 JSON 再 parse 会炸。修复后：shutdown 先校验目标，且禁止 lead；response 校验 sender 必须等于 target；approval 带原始 plan；inbox 逐行 parse JSONL，再截断每条 content。

**Q12：协议状态持久化了吗？重启会怎样？**

> 没有。`ProtocolTracker` 是内存单例，重启后协议请求状态会丢。`.team` 的花名册和 inbox 是磁盘文件，但 protocol tracker 不是。对教学演示够用；生产里要把协议请求落盘，或者和任务系统合并成统一的持久化状态。

### 第四轮：拔高，看格局

**Q13：s10 有没有提前做 s11 的 Autonomous Agents？**

> 没有。s10 只规定消息怎么说、请求怎么配对、审批怎么返回。队友不会自己扫描任务板，不会自动认领任务，也不会根据全局 backlog 自主调度。s11 才应该做"队友自己看看板，有活就认领"。s10 只是为这种自治准备协议语言。

**Q14：为什么说 s10 是多 agent 系统的"规矩层"？**

> 因为多 agent 协作不只是并发执行，还要可追踪、可拒绝、可确认。没有协议，所有协作都变成自然语言猜测；有协议后，系统能知道"请求还在 pending、谁批准了、谁拒绝了、哪个计划被允许"。这就是从"几个人同时说话"走向"团队流程"的关键一步。

**Q15：如果继续改进 s10，你会先做什么？**

> 我会先补实跑记录，观察模型是否真的愿意 `plan_submit`。然后把协议请求持久化，避免重启丢状态。再往后才考虑硬门控：在 `bash/write_file` 外包一层 policy wrapper，只有存在 approved plan 时才允许高风险操作。最后可以给协议消息加更结构化字段，比如 `risk_level`、`artifacts`、`expires_at`。

**Q16：这套设计最值得讲给面试官的取舍是什么？**

> 最值得讲的是"分层克制"。我没有改核心 loop，也没有把 s11 自治提前做掉，而是在 s09 team 的消息通道上叠了一层 protocol。关机做成硬门控，因为它能用 flag 可靠退出；计划审批先做软门控，因为硬门控需要工具级 policy，是另一个机制。知道哪些该做、哪些留到下一阶段，是这课最重要的工程判断。

### 临场提示

被问住时，往这三个方向想：

- **请求怎么配对**：靠 req_id，响应必须引用同一个请求。
- **状态怎么流转**：ProtocolTracker 维护 pending / approved / rejected。
- **边界在哪里**：关机是硬门控，计划审批是软门控；s10 是协议层，不是自治层。

面试时别只说"我加了几个工具"。更好的说法是：**我把队友通信从自然语言消息升级成了结构化协议，请求有 id、响应能配对、状态能查询；同时我清楚计划审批目前只是软门控，真正的硬拦截要到工具 policy 层。**
