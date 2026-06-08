# agent-harness-lab

跟着 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 从 s01 学到 s12，
**自己从零搭一遍 harness**，每课都做个"课后作业"证明这一阶段的机制我真的会用了。

> Agency 来自模型。Harness 让 agency 落地。

## 核心信念（整条学习路线的底层）

**循环不变，机制叠加。**
`core/` 里的那个 loop 是 s01 写完的，s02~s12 一个字都不会改，只往 `tools/ skills/ tasks/ ...` 这些外层加东西。

## 目录结构（会随课程生长）

```
agent-harness-lab/
├── core/                       # 永远不变的地基（s01 写完后锁死）
│   ├── llm.py                  # Anthropic 客户端
│   └── loop.py                 # agent_loop()
├── tools/                      # 工具集，s02 起会扩充
│   ├── bash.py
│   ├── read_file.py
│   ├── write_file.py
│   ├── todo.py
│   ├── task.py
│   ├── subagent.py
│   ├── skill.py
│   ├── compact.py
│   ├── background.py
│   └── team.py
│   └── protocols.py
├── skills/                     # 技能定义（markdown 文件），s05 新增
│   ├── git.md
│   ├── debug.md
│   └── refactor.md
├── agents/                     # 每课一个入口脚本
│   ├── s01_agent_loop.py
│   ├── s02_multi_tool.py
│   ├── s03_todo.py
│   ├── s04_subagent.py
│   ├── s05_skills.py
│   ├── s06_context_compact.py
│   ├── s07_task_system.py
│   └── s08_background.py
│   └── s09_agent_teams.py
│   └── s10_team_protocols.py
├── docs/                       # 每课一份学习笔记
│   ├── s01-notes.md
│   ├── s02-notes.md
│   ├── s03-notes.md
│   ├── s04-notes.md
│   ├── s05-notes.md
│   ├── s06-notes.md
│   ├── s07-notes.md
│   ├── s08-notes.md
│   ├── s09-notes.md
│   ├── s10-notes.md
│   └── review/                 # 大白话讲解 + 面试官视角复盘（s01~s10）
├── examples/                   # 每课一份阶段成果验证清单
│   ├── s01_demo_prompts.md
│   ├── s02_demo_prompts.md
│   ├── s03_demo_prompts.md
│   ├── s04_demo_prompts.md
│   ├── s05_demo_prompts.md
│   ├── s06_demo_prompts.md
│   ├── s07_demo_prompts.md
│   └── s08_demo_prompts.md
│   ├── s09_demo_prompts.md
│   └── s10_demo_prompts.md
├── run-records/                # 手动实跑记录 + 复盘
│   └── s04-subagent-run-review.md
├── run-outputs/                # 手动实跑产生的文件，避免污染 agents/
│   ├── s03/
│   └── s04/
├── .env.example
├── requirements.txt
└── README.md
```

## 快速开始

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # 填入 ANTHROPIC_API_KEY 和 MODEL_ID
python agents/s01_agent_loop.py
```

## 学习路线与进度

| 课 | 主题 | 格言 | 状态 |
|---|---|---|---|
| s01 | Agent Loop | One loop & Bash is all you need | ✅ |
| s02 | Tool Use | 加一个工具只加一个 handler | ✅ |
| s03 | TodoWrite | 没有计划的 agent 走哪算哪 | ✅ |
| s04 | Subagent | 大任务拆小，每个小任务干净的上下文 | ✅ |
| s05 | Skills | 用到什么知识，临时加载什么知识 | ✅ |
| s06 | Context Compact | 上下文总会满，要有办法腾地方 | ✅ |
| s07 | Task System | 大目标要拆成小任务，记在磁盘上 | ✅ |
| s08 | Background Tasks | 慢操作丢后台，agent 继续想下一步 | ✅ |
| s09 | Agent Teams | 任务太大一个人干不完，要能分给队友 | ✅ |
| s10 | Team Protocols | 队友之间要有统一的沟通规矩 | ✅ |
| s11 | Autonomous Agents | 队友自己看看板，有活就认领 | ⬜ |
| s12 | Worktree Isolation | 各干各的目录，互不干扰 | ⬜ |

## 每课的完成标准（课后作业的验收口径）

一课"结业"等价于同时满足三件事：

1. **代码**：`agents/s{NN}_*.py` 能正确跑起来
2. **笔记**：`docs/s{NN}-notes.md` 里写清楚这一课新加的机制 + 三条我相对原版故意做的差异
3. **验证**：`examples/s{NN}_demo_prompts.md` 里每条 prompt 跑出预期现象

---

## s01：Agent Loop（已完成）

一个 `while` 循环 + 一个 `bash` 工具 = 一个 Agent。

- 代码：[`agents/s01_agent_loop.py`](./agents/s01_agent_loop.py) + [`core/loop.py`](./core/loop.py) + [`tools/bash.py`](./tools/bash.py)
- 笔记：[`docs/s01-notes.md`](./docs/s01-notes.md)
- 验证：[`examples/s01_demo_prompts.md`](./examples/s01_demo_prompts.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 工具分发 | 硬编码 `run_bash(...)` | `handlers: dict[str, Callable]` dispatch map |
| 循环边界 | `while True` | `for turn in range(max_turns)` + 返回 `stop_reason` |
| 分层 | 单文件 | `core / tools / agents` 三层，core 锁死 |

---

## s02：Multi-Tool（已完成）

加一个工具只加一个 handler——core/loop.py 一行不改。

- 代码：[`agents/s02_multi_tool.py`](./agents/s02_multi_tool.py) + [`tools/read_file.py`](./tools/read_file.py) + [`tools/write_file.py`](./tools/write_file.py)
- 笔记：[`docs/s02-notes.md`](./docs/s02-notes.md)
- 验证：[`examples/s02_demo_prompts.md`](./examples/s02_demo_prompts.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 路径安全 | 无限制 | `resolve()` + `startswith()` 工作目录边界检查 |
| 工具数量 | 只加一个 | 一次加两个（read + write），更能体现"叠加"模式 |
| _print_tool_call | 统一格式 | 为每个工具定制可视化（read 显示路径，write 显示路径+行数） |

---

## s03：TodoWrite（已完成）

没有计划的 agent 走哪算哪——用 handler wrapper 闭包实现 nag 提醒，core/loop.py 一行不改。

- 代码：[`agents/s03_todo.py`](./agents/s03_todo.py) + [`tools/todo.py`](./tools/todo.py)
- 笔记：[`docs/s03-notes.md`](./docs/s03-notes.md)
- 验证：[`examples/s03_demo_prompts.md`](./examples/s03_demo_prompts.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| Nag 实现方式 | 修改 agent_loop 内部，往 messages 注入 system reminder | handler wrapper 闭包，追加到工具输出尾部 |
| 代码组织 | 单文件，TodoManager 和 handler 都内联 | `tools/todo.py` 独立模块 + `agents/` 组装 |
| Todo schema 格式 | Anthropic input_schema | OpenAI function calling format |

---

## s04：Subagent（已完成）

大任务拆小，每个小任务干净的上下文——delegate 工具启动嵌套 agent_loop，子 agent 拥有独立上下文。

- 代码：[`agents/s04_subagent.py`](./agents/s04_subagent.py) + [`tools/subagent.py`](./tools/subagent.py)
- 笔记：[`docs/s04-notes.md`](./docs/s04-notes.md)
- 验证：[`examples/s04_demo_prompts.md`](./examples/s04_demo_prompts.md)
- 实跑复盘：[`run-records/s04-subagent-run-review.md`](./run-records/s04-subagent-run-review.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 子 agent 定义位置 | 内联在 agent 入口中 | `tools/subagent.py` 独立模块 |
| 回调传递方式 | 直接传参 | 模块级变量 `set_subagent_callback()` |
| 层级可视化 | 无特殊区分 | 缩进 + 灰色（子）vs 黄色（主） |

---

## s05：Skills（已完成）

用到什么知识，临时加载什么知识——load_skill 按需加载 markdown 技能文件，不把所有知识塞进系统提示词。

- 代码：[`agents/s05_skills.py`](./agents/s05_skills.py) + [`tools/skill.py`](./tools/skill.py) + [`skills/`](./skills/)
- 笔记：[`docs/s05-notes.md`](./docs/s05-notes.md)
- 验证：[`examples/s05_demo_prompts.md`](./examples/s05_demo_prompts.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 技能格式 | JSON/YAML 结构化定义 | 纯 markdown 文件 |
| 工具设计 | 列出/加载分为两个工具 | 一个 load_skill 处理两种情况 |
| 技能发现 | 注册表或硬编码列表 | 自动扫描 skills/ 目录 |

---

## s06：Context Compact（已完成）

上下文总会满，要有办法腾地方——通过 on_tool_call 回调 + closure 实现三层压缩，core/loop.py 一行不改。

- 代码：[`agents/s06_context_compact.py`](./agents/s06_context_compact.py) + [`tools/compact.py`](./tools/compact.py)
- 笔记：[`docs/s06-notes.md`](./docs/s06-notes.md)
- 验证：[`examples/s06_demo_prompts.md`](./examples/s06_demo_prompts.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 压缩触发位置 | 修改 agent_loop for 循环头部 | on_tool_call 回调 + closure 访问 messages |
| compact 工具执行 | 直接在 loop 内检查并调用压缩 | handler 设置 flag + on_tool_call 检查 flag 并执行 |
| auto_compact 摘要格式 | 单条 system reminder | user+assistant 消息对（兼容 OpenAI 格式交替要求） |

---

## s07：Task System（已完成）

大目标要拆成小任务，记在磁盘上——用持久化任务系统替代内存 todo，支持增量操作和父子层级。

- 代码：[`agents/s07_task_system.py`](./agents/s07_task_system.py) + [`tools/task.py`](./tools/task.py)
- 笔记：[`docs/s07-notes.md`](./docs/s07-notes.md)
- 验证：[`examples/s07_demo_prompts.md`](./examples/s07_demo_prompts.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 存储方式 | 内存中 TodoManager | JSON 文件持久化 + 原子写入 |
| 操作模式 | 全量替换（每次传完整列表） | 三个增量工具（create/update/list） |
| 任务层级 | 扁平列表 | 单层父子（parent_id），树形格式化输出 |

---

## s08：Background Tasks（已完成）

慢操作丢后台，agent 继续想下一步——bash 工具新增 `run_in_background` 参数，handler wrapper 注入后台完成通知。

- 代码：[`agents/s08_background.py`](./agents/s08_background.py) + [`tools/background.py`](./tools/background.py)
- 笔记：[`docs/s08-notes.md`](./docs/s08-notes.md)
- 验证：[`examples/s08_demo_prompts.md`](./examples/s08_demo_prompts.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 后台通知注入 | 直接插入 assistant 消息 | handler wrapper 输出前缀（不改 loop） |
| 后台任务管理 | 内建调度系统 | 简单的 threading + dict（daemon 线程） |
| 扩展 bash 参数 | 修改 bash 工具定义 | deepcopy SCHEMA + agent 层扩展 |

---

## s09：Agent Teams（已完成）

任务太大一个人干不完，要能分给队友——spawn 创建持久化队友（独立线程），通过 JSONL inbox 消息总线互相通信。

- 代码：[`agents/s09_agent_teams.py`](./agents/s09_agent_teams.py) + [`tools/team.py`](./tools/team.py)
- 笔记：[`docs/s09-notes.md`](./docs/s09-notes.md)
- 验证：[`examples/s09_demo_prompts.md`](./examples/s09_demo_prompts.md)
- 实跑复盘：[`run-records/s09-agent-teams-run-review.md`](./run-records/s09-agent-teams-run-review.md)

### 相比原版的三个差异

| 差异 | 原版（s04 delegate） | 本项目（s09 队友） |
|---|---|---|
| 并发模型 | 阻塞主 agent，等子 agent 完成 | 独立线程并发，lead 可继续工作 |
| 通信方式 | 子 agent 返回结果给主 agent | JSONL inbox 消息总线，双向通信 |
| 生命周期 | 一次性，用完即弃 | 持久化，working/idle 状态循环 |

---

## s10：Team Protocols（已完成）

队友之间要有统一的沟通规矩——结构化请求-响应协议替代随意消息，优雅关机替代强杀线程。

- 代码：[`agents/s10_team_protocols.py`](./agents/s10_team_protocols.py) + [`tools/protocols.py`](./tools/protocols.py)
- 笔记：[`docs/s10-notes.md`](./docs/s10-notes.md)
- 验证：[`examples/s10_demo_prompts.md`](./examples/s10_demo_prompts.md)
- 复盘：[`docs/review/s10-review.md`](./docs/review/s10-review.md)
- 实跑复盘：[`run-records/s10-team-protocols-run-review.md`](./run-records/s10-team-protocols-run-review.md)

### 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 协议实现位置 | 修改 agent_loop 内部 | 独立 `tools/protocols.py` 模块 + team.py send 扩展 |
| 队友工具注入 | 硬编码队友工具列表 | `configure_teammate()` 工厂模式，agent 层组装 |
| 关机方式 | 保留 `__shutdown__` 强杀 | 双轨：shutdown_request 握手优先，`__shutdown__` 兜底 |
