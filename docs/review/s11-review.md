# s11 复盘：Autonomous Agents

## 大白话讲

s10 的队友已经有规矩了：关机要发请求，计划要审批，消息能带编号，lead 能查状态。

但 s10 里的队友还像"等派活的人"：

- lead 创建任务；
- lead 创建队友；
- lead 告诉队友去做什么；
- 队友做完再汇报。

s11 要解决的是下一步：队友不要一直等 lead 点名，队友空闲时应该能自己看任务板。

大白话说，s11 给团队加了一个"公共白板"：

- lead 只要往白板上贴 pending 任务；
- 队友 idle 时会自己看白板；
- 看见无主任务，就说"这个我来"；
- 认领后任务显示 `@alice` / `@bob`；
- 完成后再把任务标成 completed，然后继续找下一个。

这就是 Autonomous Agents 的核心：**队友从被动接活，变成主动找活。**

但这里有一个很重要的边界：s11 不是让基础设施偷偷替队友干活。基础设施只负责"发现白板上有活"，真正的认领仍然要让 LLM 调 `task_claim` 工具。

也就是说：

```text
基础设施扫描任务板 → 构造提示词 → 队友 LLM 调 task_claim → 工具层原子认领
```

这保留了从 s09 开始的设计原则：

> 队友是 agent，不是后台脚本；队友做事必须经过工具调用。

## 老师验收

### 材料盘点

本次 s11 新增和修改的材料是完整的：

| 类型 | 文件 | 判定 |
|---|---|---|
| 入口代码 | `agents/s11_autonomous_agents.py` | 有，基于 s10 组装，增加自主认领配置 |
| 任务工具 | `tools/task.py` | 有，新增 owner、claim、complete、find_claimable 和 RLock |
| 队友生命周期 | `tools/team.py` | 有，在 idle 循环中加入任务板扫描和空闲超时 |
| Web 入口 | `web/server.py` / `web/index.html` | 有，s11 stage、任务 owner 展示、工具卡片颜色和 flush 逻辑 |
| 学习笔记 | `docs/s11-notes.md` | 有，写清机制边界和线程安全 |
| Demo | `examples/s11_demo_prompts.md` | 有，覆盖自主认领、超时、owner、inbox 优先、协议兼容、多队友并行 |
| 实跑记录 | `run-records/s11-autonomous-agents-run-review.md` | 有，记录了主机制跑通和脏状态干扰 |

结论：**代码、笔记、demo、实跑复盘已具备；s11 学习材料完整。**

### 对照 s10 的新增机制

s10 是"协议层"：队友之间怎么说话，怎么审批，怎么关机。

s11 是"自治层"：队友空闲时怎么自己找任务，怎么认领，怎么完成。

新增机制主要有四个：

1. **任务所有权**

   `tools/task.py` 给每个任务增加 `owner` 字段。无主任务是 `owner=None`，队友认领后变成 `owner="alice"` 这种形式。`task_list` 会显示 `@alice`，让 lead 能看见任务归属。

2. **原子认领和完成**

   `task_claim(task_id)` 只能认领 `owner=None` 且 `status=pending` 的任务；认领后同时设置 `owner` 和 `status=in_progress`。

   `task_complete(task_id)` 只能由 owner 本人完成。alice 不能完成 bob 的任务。

3. **空闲自主扫描**

   `tools/team.py` 的 `_teammate_loop` 在 idle 状态下先 poll inbox，再 scan 任务板：

   ```text
   inbox 消息优先 → 无消息时扫描 pending 无主任务 → 构造自主认领 prompt → 跑 agent_loop
   ```

   这个优先级是对的。因为 inbox 是显式指令，任务板是机会型工作。

4. **空闲超时**

   队友空闲 60 秒后会给 lead 发消息并退出，避免线程一直挂着。它是生命周期收尾机制，不是调度策略本身。

### 是否遵守"循环不变，机制叠加"

通过。

`core/loop.py` 没有改。s11 仍然是在外层叠机制：

- agent 入口负责组装 system、tools、handlers；
- `team.py` 扩展队友 idle 行为；
- `task.py` 扩展任务状态机；
- `web/server.py` 扩展 s11 stage 和通知 flush；
- `core/loop.py` 继续只做模型消息和工具调用循环。

这点很关键。s11 的自治不是塞进 loop 里的，而是利用已有队友生命周期，在 idle 阶段多做一次扫描。

### 是否偷混 s12

没有。

s12 应该是 Worktree Isolation，也就是每个队友拥有自己的工作区，避免互相覆盖文件。s11 没有做这件事：

- 队友仍共享同一个 repo；
- `run-outputs/s11/` 仍是共享输出目录；
- 没有 git worktree；
- 没有每队友独立 cwd；
- 没有文件级冲突隔离。

这说明 s11 没有提前混入 s12。它只做"谁认领任务"，不做"每个人在哪个隔离目录里干活"。

### 修复后的关键验收点

我会把 s11 的主要问题分成两类：

**第一类：已经解决的硬问题。**

- `TaskManager` 加了 `threading.RLock()`。
- `create/update/claim/complete/find_claimable` 都在锁内执行。
- 多队友并发认领同一个任务时，只有一个成功。
- `_save()` 的 `.tmp → tasks.json` 原子写入在锁内完成，不再出现并发 rename 抢同一个 tmp 文件。
- Web 和 CLI 都会等待工作中的队友，并把队友通知注入回消息历史。

这些修完后，s11 的核心状态机是稳的。

**第二类：学习阶段可以接受的边界。**

- 自主认领是 LLM 软执行：LLM 看到任务后理论上可能不调 `task_claim`。
- 计划审批仍继承 s10 的软门控：高风险操作是否先 `plan_submit` 主要靠提示词。
- 任务持久化了，但队友线程本身不能跨进程恢复；重启前仍建议清理 `.team`。
- 文件写入没有隔离，多个队友写同一个文件仍可能冲突；这是 s12 要解决的问题。

结论：**s11 机制主体通过，边界说明到位；实跑记录也已补齐。**

## 机制边界

### 1. 软自治 vs 硬状态机

s11 最重要的边界是：

> "发现任务并提示队友"是软自治，"认领任务并改变状态"是硬状态机。

软的部分：

- idle 循环看到 `find_claimable()` 有任务；
- 构造 `[自主认领]` prompt；
- LLM 决定是否调用 `task_claim`；
- LLM 决定怎么执行任务、是否调用 `task_complete`。

硬的部分：

- `task_claim` 在锁内检查 pending 和 owner；
- `task_claim` 在同一临界区内设置 owner 和 in_progress；
- `task_complete` 校验 owner；
- 每个 owner 只能有一个 in_progress；
- 并发认领同一个任务只会有一个成功。

这就是 s11 的工程价值：**LLM 可以不稳定，但状态机不能不稳定。**

### 2. `find_claimable()` 不是预约

`find_claimable()` 返回的是快照。两个队友可能同时看见同一个 pending 任务。

这不是 bug，前提是 `claim()` 必须可靠。s11 修复后正是这个模式：

```text
alice 和 bob 都看到 #1 pending
alice 调 task_claim(#1) 成功
bob 调 task_claim(#1) 失败：任务已不是 pending / 已被认领
```

所以 `find_claimable()` 负责发现机会，`claim()` 负责最终裁决。

### 3. inbox 优先级高于任务板

队友 idle 时先读 inbox，再扫描任务板。这是正确边界：

- inbox 是 lead 或其他队友的显式消息；
- 任务板是无主 backlog；
- 显式指令应该优先于机会型自主工作。

如果反过来，队友可能在 lead 刚发来紧急指令时先跑去认领别的任务，协作体验会变差。

### 4. s11 不是调度器大脑

s11 没有做全局最优调度，也没有任务优先级、技能匹配、负载均衡、失败重试。

它的策略很朴素：

```text
空闲队友发现第一个 claimable 任务 → 提示 LLM 认领
```

这对学习阶段很好，因为机制足够清楚。但如果面试官追问生产化，你要承认：这只是最低可用自治，不是完整调度系统。

### 5. s11 不是文件隔离

s11 能避免"两个队友认领同一个任务"，但不能避免"两个不同任务写同一个文件"。

例如：

```text
#1 写 run-outputs/s11/a.txt
#2 也写 run-outputs/s11/a.txt
```

任务系统会允许 alice 和 bob 各自认领不同任务，但文件层冲突仍然存在。这正是 s12 Worktree Isolation 要解决的范围。

## 如果我是面试官

### 第一轮：确认你懂本质

**Q1：s11 的核心变化是什么？**

> s11 让队友从"被 lead 分配任务"变成"空闲时自己扫描任务板并认领任务"。核心新增是任务 owner、`task_claim`、`task_complete`，以及队友 idle 循环里的自主扫描。它不是让模型变聪明，而是让队友有了主动找活的入口。

**Q2：s11 和 s10 的关系是什么？**

> s10 是协议层，解决队友之间如何发请求、审批、关机；s11 是自治层，解决队友如何从全局任务板主动拿活。s11 继承 s10 的协议工具，但新增的是任务认领和 idle 扫描，不是新的通信协议。

**Q3：为什么不让基础设施直接 claim 并执行？**

> 因为项目一直保持"队友通过工具操作"的模式。如果基础设施直接 claim，队友就变成脚本执行器，不再是 agent。现在基础设施只发现任务并构造 prompt，真正的状态变更仍由 LLM 调 `task_claim` 完成，这样可以保留 agent 的决策过程和工具调用轨迹。

### 第二轮：挖实现

**Q4：`owner` 字段解决了什么？**

> 它解决任务归属。没有 owner 时，只能看到 pending / in_progress / completed，不知道谁在做。加了 owner 后，任务可以显示 `@alice`，`task_complete` 也能校验只有 owner 才能完成自己的任务。

**Q5：为什么 s11 要把 in_progress 从全局单个改成按 owner 计数？**

> 因为多队友并行时，全局只能一个 in_progress 会把团队并发废掉。s11 的合理约束是每个 owner 同一时间最多一个 in_progress，这样 alice 和 bob 可以各做一个任务，但 alice 自己不能同时认领两个任务。

**Q6：`task_claim` 为什么必须加锁？**

> 因为多个队友线程可能同时认领任务。`claim()` 是读-改-写操作：先检查任务是否 pending、是否无 owner，再设置 owner/status，再保存文件。如果没有锁，两个线程可能同时通过检查，或者同时写同一个 `tasks.tmp` 导致文件写入异常。`RLock` 把这段变成临界区，保证只有一个线程能完成认领。

**Q7：为什么用 `RLock` 而不是普通 `Lock`？**

> 因为 `claim/complete` 在锁内会调用 `format()`，`format()` 又会读任务列表并调用 `_summary()`。用可重入锁可以避免同一线程二次进入锁时死锁。普通 `Lock` 如果也包住 format 相关读操作，容易把自己锁死。

**Q8：`find_claimable()` 返回快照会不会有问题？**

> 不会，只要 `claim()` 是最终裁决。两个队友可以看到同一个可认领任务，但只有第一个成功 claim 的队友能把它改成 in_progress。第二个队友再 claim 会失败。这是典型的"先发现，再 CAS/锁内提交"模式。

### 第三轮：边界 / 一致性

**Q9：s11 的自治是硬保证吗？**

> 不是。自治行为本身是软的：LLM 看到提示后可能不调 `task_claim`，也可能执行不完整。但任务状态机是硬的：只要调用 `task_claim`，工具层会保证 owner、status、in_progress 约束和并发安全。

**Q10：s11 有没有破坏 s09/s10 的生命周期？**

> 没有。s11 只是把 idle 循环扩展成 inbox 优先、任务板扫描其次、超时退出最后。队友仍然是 working/idle/poll 的持久线程；普通 send 仍然可用；s10 的 shutdown_request / plan_submit 也继续通过 configure_teammate 注入。

**Q11：s11 有没有提前做 s12？**

> 没有。s11 没有 worktree，没有独立 cwd，没有文件隔离。它只能保证任务认领不冲突，不能保证文件写入不冲突。两个不同任务如果都写同一个文件，s11 仍然挡不住，这应该留给 s12。

**Q12：重启后 s11 能恢复自治队友吗？**

> 不能完全恢复。任务数据持久化在 `data/tasks.json`，但队友线程是进程内线程，重启后不会自动复活。`.team` 里可能有旧花名册状态，所以 demo 前清理 `.team data/tasks.json` 是合理的。生产化要做队友恢复或 stale roster 清理。

### 第四轮：拔高，看格局

**Q13：s11 最值得讲的设计取舍是什么？**

> 最值得讲的是"软执行 + 硬状态"。我不假设 LLM 一定可靠执行，但把关键状态变更放到工具层，用锁和状态机保证不会重复认领、不会跨 owner 完成、不会并发写坏任务文件。这样既保留 agent 自主性，又把系统一致性放在可控代码里。

**Q14：如果继续改进 s11，你会先做什么？**

> 我会先补实跑记录，验证 demo 里的 6 个场景。然后加任务优先级和失败重试，让队友认领失败后能自动找下一个任务。再往后做 stale teammate 清理、任务和队友状态恢复。文件冲突隔离要等 s12，用 worktree 或独立工作目录解决。

**Q15：s11 的工程风险是什么？**

> 第一是 LLM 可能不按提示 claim/complete，所以 demo 要看真实行为。第二是多队友共享文件系统，可能写同一个文件。第三是队友自动退出和 lead 等待窗口之间可能有时序差。第四是任务状态持久化了，但队友线程没有持久化。

**Q16：你怎么一句话总结 s11？**

> s11 把团队从"lead 派活"推进到"队友自己看板拿活"；基础设施负责发现机会，LLM 负责通过工具行动，任务状态机负责硬一致性。

### 临场提示

被问住时，抓住这三句话：

- **新增了 owner**：任务不只是状态，还有归属。
- **新增了 claim/complete**：认领和完成进入工具层状态机。
- **新增了 idle scan**：队友空闲时自己找活，但不直接改状态。

面试时不要只说"我加了自动扫描"。更好的说法是：**我把 s10 的有规矩团队推进到 s11 的自主团队：队友空闲时扫描任务板，但真正认领由 `task_claim` 这个带锁的状态机完成，所以自治行为可以是软的，系统一致性必须是硬的。**
