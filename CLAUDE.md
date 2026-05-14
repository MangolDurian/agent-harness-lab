# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

跟着 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 从零搭 agent harness，每课一个阶段（s01~s12），逐步叠加机制。

核心原则：**循环不变，机制叠加。** `core/loop.py` 在 s01 写完后锁死，s02~s12 一行不改，只往外层加东西。

## 常用命令

```bash
source .venv/bin/activate          # 激活虚拟环境
python agents/s{NN}_*.py           # 运行某个阶段的 agent（如 python agents/s03_todo.py）
```

无构建/测试/ lint 流程。验证方式是手动跑 `examples/s{NN}_demo_prompts.md` 中的 prompt。

## 架构

三层分离，依赖方向单向：agents → core + tools。

```
core/loop.py    — agent_loop() 循环引擎，永不修改
core/llm.py     — OpenAI 兼容客户端（智谱 AI / GLM），环境变量驱动
tools/*.py      — 每个工具暴露 SCHEMA + run()，独立模块
agents/s{NN}_*.py — 入口脚本，只做组装：导入 core + tools，拼 SYSTEM/TOOLS/HANDLERS
docs/           — 每课学习笔记
examples/       — 每课验证 prompt
run-records/    — 手动实跑记录 + 复盘
run-outputs/    — 手动实跑产生的文件，避免污染 agents/
```

### 工具模式

每个 `tools/xxx.py` 遵循统一模式：
- `SCHEMA`：OpenAI function calling 格式的工具定义
- `run(**kwargs) -> str`：工具执行函数

加一个工具 = 加一个模块 + 在 agent 的 TOOLS/HANDLERS 里各加一行。

### Agent 组装模式

每个 `agents/s{NN}_*.py` 做的事：
1. 定义 `SYSTEM` 提示词
2. 列出 `TOOLS = [各工具的 SCHEMA]`
3. 映射 `HANDLERS = {"tool_name": tool.run, ...}`
4. 调用 `agent_loop(messages, system=SYSTEM, tools=TOOLS, handlers=HANDLERS)`
5. REPL 循环读取用户输入

### 关键技术选型

- **API 格式**：OpenAI 兼容（非 Anthropic），通过 `BASE_URL` 指向智谱 AI
- **工具调用**：`tool_calls` 数组 + `role="tool"` 消息（OpenAI 风格）
- **安全防护**：bash 危险命令黑名单、file 工具路径穿越检查（`resolve()` + `startswith()`）
- **输出截断**：工具输出上限 50000 字符，防止撑爆上下文

## 环境配置

`.env` 文件需要：
- `API_KEY`：智谱 AI 密钥
- `MODEL_ID`：模型名（默认 `glm-5.1`）
- `BASE_URL`：API 地址（默认 `https://open.bigmodel.cn/api/paas/v4`）

## 每课完成标准

一课结业 = 同时满足三件事：
1. **代码**：`agents/s{NN}_*.py` 能正确跑
2. **笔记**：`docs/s{NN}-notes.md` 写清新机制 + 相比原版的三个差异
3. **验证**：`examples/s{NN}_demo_prompts.md` 每条 prompt 跑出预期现象

## 目录整洁约定

- `agents/` 只放入口脚本，不放运行产物、复盘文档或临时文件。
- 课程笔记放 `docs/`。
- 验证 prompt 放 `examples/`。
- 手动运行的复盘记录放 `run-records/`。
- agent 运行生成的文件放 `run-outputs/`。
