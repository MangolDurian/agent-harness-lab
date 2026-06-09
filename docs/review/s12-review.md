# s12 复盘：Worktree Isolation

## 大白话讲

s11 的队友已经会自己看任务板拿活了，但所有人还挤在同一个工作目录里。

这会带来一个很现实的问题：alice 和 bob 认领的是两个不同任务，但如果都改同一个文件，最后还是会互相污染。任务板只能保证"谁在做哪件事"，不能保证"每个人在哪个干净房间里做事"。

s12 解决的就是这个问题。

大白话说，s12 给每个重要任务分了一间独立工作间：

- lead 创建任务；
- lead 给任务绑定一个 git worktree；
- 任务板上显示 `[wt:auth-refactor]`；
- 队友空闲扫描到这个任务并认领；
- 队友的 `bash/read_file/write_file` 自动切到这个 worktree；
- 队友写文件时，改动落在 `.worktrees/auth-refactor/`，不会落到主目录。

所以 s12 的核心不是"队友更聪明"，而是"队友干活的位置被隔离"。

s11 管的是：

```text
谁来做这个任务
```

s12 管的是：

```text
这个任务在哪个独立目录里做
```

这就是 Worktree Isolation：**各干各的目录，互不干扰。**

## 老师验收

### 材料盘点

本次 s12 的主要材料已经齐：

| 类型 | 文件 | 判定 |
|---|---|---|
| 入口代码 | `agents/s12_worktree_isolation.py` | 有，基于 s11 组装，增加 worktree 工具和隔离提示 |
| Worktree 工具 | `tools/worktree.py` | 有，管理 create/remove/keep/list/exec 和 worktree-aware handler |
| 任务工具 | `tools/task.py` | 有，新增 `worktree` 字段和 bind/unbind |
| 队友生命周期 | `tools/team.py` | 有，在 idle scan 认领绑定任务时替换隔离 handler |
| Web 入口 | `web/server.py` / `web/index.html` | 有，新增 s12 stage 和 worktree 相关展示 |
| 学习笔记 | `docs/s12-notes.md` | 有，写清双面架构、状态机和三个差异 |
| Demo | `examples/s12_demo_prompts.md` | 已优化，覆盖创建、隔离执行、队友自动隔离、清理、事件和 s11 兼容 |
| 实跑记录 | `run-records/s12-worktree-isolation-run-review.md` | 有，记录了通过项、脏状态影响和待复测边界 |

结论：**s12 的代码、笔记、demo、实跑复盘已具备；自动 worktree handler 替换还需要一轮干净环境复测来完全闭环。**

### 对照 s11 的新增机制

s11 已经完成了 Autonomous Agents：

- 任务有 owner；
- 队友 idle 时扫描任务板；
- `task_claim` 原子认领；
- `task_complete` 由 owner 完成；
- inbox 优先于任务扫描；
- 空闲超时退出。

s12 没有重写这套自治，而是在它上面叠了一层"执行目录隔离"：

1. **WorktreeManager**

   `tools/worktree.py` 管理 `.worktrees/` 下的 git worktree 生命周期：

   - `worktree_create(name, task_id?)`
   - `worktree_remove(name, force?, complete_task?)`
   - `worktree_keep(name)`
   - `worktree_list()`
   - `worktree_exec(name, command)`

2. **任务绑定 worktree**

   `tools/task.py` 给任务增加 `worktree` 字段。绑定后，`task_list` 会显示：

   ```text
   #1 [ ] [wt:auth-refactor] 重构认证模块
   ```

   这说明任务板仍然是控制面，但它现在知道任务应该在哪个执行面工作。

3. **隔离 handler**

   `tools/worktree.py` 提供工厂函数：

   - `make_worktree_bash_handler(worktree_path)`
   - `make_worktree_read_handler(worktree_path)`
   - `make_worktree_write_handler(worktree_path)`

   队友认领绑定 worktree 的任务时，`tools/team.py` 会临时替换这三个 handler。这样 `core/loop.py` 完全不知道 worktree 的存在。

4. **显式 worktree 执行**

   lead 和队友都可以使用 `worktree_exec(name, command)`，直接在指定 worktree 中执行命令。这条路径不依赖 idle scan，是显式隔离入口。

### 是否遵守"循环不变，机制叠加"

通过。

`core/loop.py` 没有被改动。s12 的新增机制全部在外层：

- `agents/s12_worktree_isolation.py` 负责组装新的 tools/handlers/system prompt；
- `tools/worktree.py` 负责 worktree 生命周期；
- `tools/task.py` 负责任务和 worktree 的绑定关系；
- `tools/team.py` 在队友 idle scan 路径中替换 handler；
- `core/loop.py` 继续只做消息循环和工具调用。

这点是 s12 最重要的结构验收：**隔离是 handler 层叠加出来的，不是 loop 层硬塞进去的。**

### 是否提前混入下一阶段能力

没有明显越界。

s12 继承了 s10 的协议和 s11 的自治，这是合理的，因为它是建立在 s11 基础上的阶段。但 s12 自己没有新增一套更复杂的自治调度，也没有把 merge/review/CI 这些后续生产化能力提前混进来。

s12 的范围很清楚：

```text
任务可以绑定 worktree
绑定任务被队友自动认领时，执行目录被隔离
```

它没有做：

- 自动合并 worktree 分支；
- 自动解决冲突；
- 自动代码评审；
- 自动测试矩阵；
- 多 worktree 之间的依赖编排；
- 跨进程恢复队友线程。

所以 s12 没有把下一阶段的工程系统提前塞进来，边界是干净的。

### 修复后的关键验收点

这轮 s12 最关键的修复有三处。

**第一，worktree 相对路径修复到位。**

早期 bug 是 `Path("test.py").resolve()` 会按进程当前目录解析，导致 worktree handler 里的相对路径没有落到 worktree，而是跑去主目录解析。

修复后 `_resolve_worktree_path(file_path, root)` 先把相对路径拼到 worktree root，再 `resolve()`：

```text
test.py → .worktrees/auth-refactor/test.py
src/main.py → .worktrees/auth-refactor/src/main.py
```

同时路径穿越仍会被拦截：

```text
../outside.py → 错误：路径穿越已拦截
```

这是硬边界，必须通过。

**第二，demo 已改为验证 idle scan 路径。**

handler 自动替换只发生在队友空闲扫描任务板、发现绑定 worktree 的任务时。

如果 demo 直接在 `spawn` 初始 prompt 里让队友写文件，那走的是初始 prompt 路径，不能证明 worktree-aware handler 生效。

现在 demo 明确让队友先等待任务，再通过 idle scan 自动发现绑定任务，这个验证路径是对的。

**第三，清理命令补了 git worktree 状态。**

只删 `.worktrees/` 目录不够，因为 git 还可能残留 worktree metadata 和 `wt/*` 分支。

demo 现在会先 `git worktree prune`，再清理 `wt/*` 分支和本地状态。这个对重复实跑很重要。

结论：**s12 主机制通过静态验收，修复点也对；实跑已证明显式隔离和生命周期可用，但队友自动 worktree 隔离还需要干净环境复测。**

### 实跑后的补充判断

实跑记录见 `run-records/s12-worktree-isolation-run-review.md`。

这轮实跑里，`worktree_exec` 显式隔离、主目录不泄露、keep/remove 生命周期、events 日志、普通 s11 自治兼容都通过了。

但任务板不是干净状态，新任务从 `#18/#19/#20` 开始，导致 demo 中“任务 1 / 任务 2”的语义发生偏移。最后的 direct spawn 边界测试也被仍在 idle 的 bob 抢任务干扰。

因此最终验收口径要更精确：

```text
显式 worktree 隔离：通过
worktree 生命周期：通过
s11 兼容路径：通过
direct spawn 不自动隔离：观察成立
绑定 worktree 的 idle scan 自动 handler 替换：需要补跑
```

## 机制边界

### 1. 控制面 vs 执行面

s12 的架构可以拆成两面：

```text
Control plane: data/tasks.json
Execution plane: .worktrees/{name}/
```

控制面回答：

- 任务是什么？
- 任务状态是什么？
- 谁认领了任务？
- 任务绑定哪个 worktree？

执行面回答：

- 文件实际在哪改？
- 命令在哪个 cwd 里跑？
- 哪个 git 分支承载这次改动？

这两面通过任务的 `worktree` 字段连接，但不能混为一谈。

### 2. 自动隔离只覆盖 idle scan 认领路径

这是 s12 最容易误解的地方。

自动替换 `bash/read_file/write_file` handler 的路径是：

```text
队友 idle → 扫描任务板 → 找到绑定 worktree 的 pending 任务
→ 构造自主认领 prompt → 使用 worktree-aware handlers 跑 agent_loop
```

所以这条路径会自动隔离。

但下面这些路径不会自动替换 handler：

- `spawn(name, role, prompt)` 的初始 prompt；
- 普通 `send(to, content)` 后触发的 inbox 工作；
- lead 自己直接调用普通 `write_file`。

这些路径如果要隔离，应使用 `worktree_exec(name, command)`，或者让任务走 idle scan 自动认领。

### 3. `worktree_exec` 是显式隔离入口

`worktree_exec(name, command)` 不依赖队友是否 idle，也不依赖任务是否被认领。它直接把 cwd 设置到目标 worktree。

所以它适合验证和显式操作：

```text
worktree_exec("auth-refactor", "pwd")
worktree_exec("auth-refactor", "cat test_auth.py")
```

这条路径能证明 worktree 目录存在、文件确实写在隔离目录里。

### 4. worktree 隔离不是合并系统

s12 只保证"改动先隔离"，不保证"改动最后优雅合并"。

它不会自动：

- merge `wt/auth-refactor`；
- rebase 分支；
- 检测冲突；
- 生成 PR；
- 运行测试矩阵；
- 判断改动是否应该保留。

所以面试时要讲清楚：s12 是执行隔离，不是完整代码交付流水线。

### 5. 注册表不是 git 的唯一真相

`.worktrees/index.json` 记录了 name、branch、task_id、status 等元数据；git 自己也维护 worktree metadata。

两边可能因为手动删除目录、强制删分支、异常退出而不同步。因此清理时需要：

```text
git worktree prune
删除 wt/* 分支
删除 .worktrees/
清理 .team 和 data/tasks.json
```

这不是 s12 失败，而是 git worktree 本身就有外部状态。

### 6. LLM 执行仍是软的，目录边界是硬的

s12 仍然继承 s11 的软自治：

- 队友看到任务后，理论上可能不认领；
- 认领后，理论上可能写错文件；
- 高风险操作是否提交计划，仍依赖 s10 的提示词和协议。

但只要它调用的是 worktree-aware handler，路径边界是硬的：

- 相对路径以 worktree root 为基准；
- 路径穿越被拦截；
- 普通写入不会落到主目录。

这就是 s12 的工程价值：**模型可以犯执行错误，但目录边界不能悄悄失效。**

### 7. `kept` 和 `removed` 是生命周期状态，不是任务状态

任务状态仍然是：

```text
pending → in_progress → completed
```

Worktree 状态是：

```text
active → kept | removed
```

`worktree_keep` 只是保留隔离目录，不代表任务完成。

`worktree_remove(..., complete_task=true)` 才会尝试同时完成绑定任务。

两套状态机有关联，但不是一套东西。

## 如果我是面试官

### 第一轮：确认你懂本质

**Q1：s12 的核心变化是什么？**

> s12 给任务增加 git worktree 隔离。s11 解决谁来做任务，s12 解决任务在哪个独立目录里做。绑定 worktree 的任务被队友自动认领时，队友的 bash/read/write handler 会切到对应 worktree，从而避免不同任务互相污染主目录。

**Q2：s12 和 s11 的关系是什么？**

> s11 是自治层，让队友空闲时自己看任务板认领任务；s12 是隔离层，让被认领的任务可以绑定独立 worktree。s12 没有重写 s11 的自治，只是在 s11 的 idle scan 认领路径上叠加 worktree-aware handler。

**Q3：为什么不直接修改 `core/loop.py` 传 cwd？**

> 因为项目原则是 `core/loop.py` 从 s01 后不改。s12 用 handler 工厂函数解决 cwd 问题：同一个工具名 `write_file`，在普通队友里是默认 handler，在绑定 worktree 的任务里是 worktree-aware handler。loop 不需要知道这件事。

### 第二轮：挖实现

**Q4：`tools/worktree.py` 负责什么？**

> 它负责 worktree 生命周期：创建 git worktree、写注册表、绑定任务、删除或保留 worktree、列出状态、在指定 worktree 执行命令，并提供 worktree-aware 的 bash/read/write handler 工厂函数。

**Q5：任务里的 `worktree` 字段有什么用？**

> 它把控制面和执行面连接起来。任务板仍然存任务状态和 owner，但多了 `worktree` 字段后，队友认领任务时可以知道应该在哪个 worktree 工作，`task_list` 也能显示 `[wt:name]`。

**Q6：为什么相对路径解析是一个关键 bug？**

> 因为 `Path("test.py").resolve()` 默认按进程 cwd 解析，不会自动按 worktree cwd 解析。如果 worktree read/write handler 也这么写，相对路径会跑到主目录，隔离就失效了。修复方式是相对路径先拼到 worktree root，再 resolve，并检查结果仍在 root 内。

**Q7：为什么 `worktree_exec` 还要保留？队友不是会自动隔离吗？**

> 自动隔离只发生在 idle scan 认领绑定任务的路径。`worktree_exec` 是显式入口，适合 lead 验证、手动操作、或者不经过队友自治时仍然想在指定 worktree 中执行命令。

### 第三轮：边界 / 一致性

**Q8：直接 `spawn` 一个队友让她写文件，会自动进 worktree 吗？**

> 不会。`spawn` 的初始 prompt 使用默认 handler。自动替换 handler 的路径是 idle scan 发现绑定 worktree 的任务。如果直接分配任务又想隔离，要么让任务走任务板自动认领，要么显式使用 `worktree_exec`。

**Q9：s12 能防止所有文件冲突吗？**

> 不能。它能防止不同 worktree 内的工作互相污染主目录，但最终合并分支时仍可能冲突。s12 是隔离执行，不是冲突解决系统。

**Q10：`kept` 和 `removed` 有什么区别？**

> `kept` 表示 worktree 仍保留，适合继续检查改动；`removed` 表示 worktree 已清理。它们是 worktree 生命周期状态，不等于任务状态。任务是否 completed 仍由 task 状态机决定。

**Q11：s12 有没有破坏 s09/s10/s11 的机制？**

> 没有。s09 的队友生命周期还在，s10 的协议还在，s11 的自主认领还在。s12 只是给绑定 worktree 的任务增加隔离执行目录，并且通过 handler 替换实现，没有改核心 loop。

**Q12：你会怎么验证 s12？**

> 我会先清理 `.team/data/tasks.json/.worktrees` 和 git worktree metadata；然后创建两个任务和两个 worktree；用 `worktree_exec` 在不同 worktree 写不同文件，确认主目录没有这些文件；再让队友通过 idle scan 自动认领绑定任务，确认它写出的文件落在 `.worktrees/{name}`；最后验证 keep/remove/events，以及不绑定 worktree 的 s11 任务仍然能正常认领。
