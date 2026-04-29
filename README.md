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
│   └── write_file.py
├── agents/                     # 每课一个入口脚本
│   ├── s01_agent_loop.py
│   └── s02_multi_tool.py
├── docs/                       # 每课一份学习笔记
│   ├── s01-notes.md
│   └── s02-notes.md
├── examples/                   # 每课一份阶段成果验证清单
│   ├── s01_demo_prompts.md
│   └── s02_demo_prompts.md
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
| s03 | TodoWrite | 没有计划的 agent 走哪算哪 | ⬜ |
| s04 | Subagent | 大任务拆小，每个小任务干净的上下文 | ⬜ |
| s05 | Skills | 用到什么知识，临时加载什么知识 | ⬜ |
| s06 | Context Compact | 上下文总会满，要有办法腾地方 | ⬜ |
| s07 | Task System | 大目标要拆成小任务，记在磁盘上 | ⬜ |
| s08 | Background Tasks | 慢操作丢后台，agent 继续想下一步 | ⬜ |
| s09 | Agent Teams | 任务太大一个人干不完，要能分给队友 | ⬜ |
| s10 | Team Protocols | 队友之间要有统一的沟通规矩 | ⬜ |
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
