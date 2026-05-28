# s05 实跑复盘：Skills 按需加载

本记录来自一次手动运行 `agents/s05_skills.py` 后的复盘。

## 本章核心

s05 学的不是“多读几个 markdown 文件”，而是：

> agent 不需要一开始把所有领域知识塞进系统提示词，而是在任务需要时通过 `load_skill` 把对应技能文件加载进上下文。

流程可以简化为：

```text
主 agent_loop
  -> 模型判断当前任务需要某类知识
  -> 调用 load_skill(name)
      -> tools/skill.py 读取 skills/{name}.md
      -> 技能全文作为 tool 消息回灌到 messages[]
  -> 模型参考技能内容继续调用其他工具
```

这和 s04 的 `delegate` 叠加后，形成了一个关键点：

```text
主 agent 加载过的 skill 不会自动进入子 agent 上下文
子 agent 如果需要技能，要么由主 agent 把要点写进 task，要么自己调用 load_skill
```

当前实现选择两种能力都支持：主 agent 可以在 `delegate(task)` 中写明原则，子 agent 也拥有 `load_skill` 工具。

## 原始问答记录摘录

### 1. 加载 git 技能并拟定提交信息

输入：

```text
加载 git 技能，查看当前 git 状态，并根据技能规范拟定一个中文提交信息。不要执行 git add 或 git commit。
```

输出摘录：

```text
[load_skill] 加载技能：git
# Git 工作流

$ git status
On branch main
Your branch is up to date with 'origin/main'.
Changes not staged...

$ git diff CLAUDE.md
$ git diff requirements.txt
$ ls -la web/
$ head -30 web/server.py
```

模型最终汇总：

```text
当前 Git 状态：
- 已修改（未暂存）：CLAUDE.md、requirements.txt
- 未跟踪：.idea/、web/（含 index.html、server.py）

建议提交信息：
新增：Web 调试前端与 Git 提交规范

- 新增 web/server.py：FastAPI WebSocket 服务器，实时展示 agent 工具调用与状态
- 新增 web/index.html：调试前端页面
- 新增 requirements.txt 依赖：fastapi、uvicorn、websockets
- 文档 CLAUDE.md：补充 Git 提交规范章节
```

复盘：

- `load_skill("git")` 被正确触发，说明系统提示中的技能触发条件生效。
- agent 遵守了“不执行 git add 或 git commit”的限制，只读了状态和 diff。
- 模型主动识别 `.idea/` 不应提交，符合项目约定。
- 提交信息格式使用了 `git.md` 中的 `<类型>：<简述>`，但和 `CLAUDE.md` 中更具体的阶段提交格式不完全一致；这是两个规范之间的优先级问题，后续可以统一。

### 2. 调试 `/tmp/test.txt` 写入问题

输入：

```text
帮我排查一下为什么 echo 'hello' > /tmp/test.txt 这个命令写入失败了。
```

输出摘录：

```text
[load_skill] 加载技能：debug
# 调试策略

$ echo 'hello' > /tmp/test.txt 2>&1; echo "Exit code: $?"
Exit code: 0

$ cat /tmp/test.txt 2>&1; echo "---"; ls -la /tmp/test.txt ...
hello
---
-rw-r--r--@ 1 mangguo wheel 6 May 28 11:16 /tmp/test.txt
```

模型最终结论：

```text
echo 'hello' > /tmp/test.txt 实际上写入成功了，并没有失败。
```

复盘：

- 这次真实运行纠正了原验证清单里的预期：`bash` 工具本身没有把 `/tmp` 写入拦截掉。
- 路径边界检查存在于 `read_file` / `write_file`，不在 `bash`。
- 这个 prompt 仍然有价值，因为它验证了 debug 技能会触发，并且模型按“复现问题 -> 验证假设”的路径排查。
- 如果要测试路径安全策略，prompt 应改成让模型调用 `write_file` 写 `/tmp/test.txt`，而不是让 shell 重定向写 `/tmp`。

### 3. 加载未知技能

输入：

```text
加载一个叫做 python 的技能。
```

输出摘录：

```text
[load_skill] 加载技能：python
未知技能 'python'。

可用技能：
- debug: 调试策略
- git: Git 工作流
- refactor: 重构指南
```

复盘：

- 未知技能没有导致循环中断，而是返回可用列表。
- `_list_skills()` 的自动发现生效，新增技能时理论上只需增加 `skills/*.md` 文件。
- 模型没有盲目编造 python 技能内容，而是诚实说明当前没有这个技能。

### 4. 加载 refactor 技能并委托子 agent 重构

输入：

```text
加载 refactor 技能，然后把 tools/bash.py 按照重构指南中的原则优化一下。
用 delegate 委托子 agent 执行具体的代码修改，在 task 中写清楚重构原则。
```

输出摘录：

```text
[load_skill] 加载技能：refactor
[read_file] tools/bash.py
[todo_write] 4 items
[delegate] 委托任务：重构文件 /Users/mangguo/code/2026/Apr/agent-harness-lab/tools/bash.py，按照以下重构原则逐一执行...

重构完成，已将结果写回 `tools/bash.py`。
```

最终 `tools/bash.py` 的主要变化：

```text
120 -> COMMAND_TIMEOUT_SECONDS
50_000 -> MAX_OUTPUT_LENGTH
安全检查逻辑 -> _is_dangerous(command)
输出截断逻辑 -> _truncate_output(text)
删除部分逐行解释型注释
```

复盘：

- `refactor` 技能被正确加载。
- 主 agent 先读文件、建 todo，再委托子 agent，体现了 s03 + s04 + s05 的叠加。
- 委托任务中写入了重构原则，避免子 agent 只拿到模糊目标。
- 子 agent 实际完成了代码写入，说明 `delegate` 可以承担局部实现任务。

## 运行中暴露的问题

### 1. 原 s05 验证清单对 `/tmp` 的预期不准确

真实运行证明：

```text
echo 'hello' > /tmp/test.txt
```

会成功。原因是它走的是 `bash` 工具，而 `bash.run()` 只设置工作目录，不做路径边界拦截。

真正会拦截工作目录外路径的是 `tools/read_file.py` 和 `tools/write_file.py`。

### 2. 验证命令被危险命令黑名单误伤

重构后有几次验证命令形如：

```text
python -c "from tools.bash import run; ... run('sudo rm -rf /') ..."
```

虽然危险命令只是 Python 字符串内部的测试输入，但外层 `bash` 工具在执行前会先扫描整条 shell 命令文本。由于命令文本包含 `sudo`，所以直接被 `_DANGEROUS` 黑名单拦截。

这说明：

- 黑名单是简单子串匹配，不理解 shell / Python 字符串语义。
- 这种保守策略适合教学 harness，但会让某些安全逻辑测试变得不方便。
- 后续测试危险命令时，可以通过专门的 Python 测试文件或避开被外层 shell 扫描的字面量来验证。

### 3. nag 提醒会污染验证输出

连续多次非 `todo_write` 工具调用后，工具输出尾部出现：

```text
[提醒] 你已经连续 N 次工具调用没有更新待办列表了。考虑调用 todo_write 来追踪你的进度。
```

这验证了 s03 的 nag wrapper 仍然在 s05 生效，但也带来一个副作用：当工具调用用于细粒度验证时，提醒文本会和真实命令输出混在一起。

这不是功能错误，但会影响判断测试输出。后续可以考虑让 nag 只在主任务执行阶段触发，或者在验证类命令中更及时更新 todo。

### 4. `load_skill` 输出缺少截断与去重

本次技能文件较短，没有造成问题。但从机制上看：

- 每次 `load_skill` 都会把技能全文注入上下文。
- 同一个技能重复加载会重复占用上下文。
- `tools/skill.py` 当前没有类似 `read_file.py` 的最大长度截断。

这正好引出 s06 的主题：上下文总会满，要有办法腾地方。

## 输出和代码对应关系

### `load_skill` 的工具注册

对应 `agents/s05_skills.py`：

```python
TOOLS = [
    bash.SCHEMA,
    read_file.SCHEMA,
    write_file.SCHEMA,
    todo.SCHEMA,
    subagent.SCHEMA,
    skill.SCHEMA,
]

_BASE_HANDLERS = {
    "bash": bash.run,
    "read_file": read_file.run,
    "write_file": write_file.run,
    "todo_write": todo.run,
    "delegate": subagent.run,
    "load_skill": skill.run,
}
```

### 技能文件加载

对应 `tools/skill.py`：

```python
skill_file = (_SKILLS_DIR / name).with_suffix(".md").resolve()

if not skill_file.is_relative_to(_SKILLS_DIR.resolve()):
    return f"错误：技能名称 '{name}' 不合法。"

if not skill_file.exists():
    return f"未知技能 '{name}'。\n\n" + _list_skills()

return skill_file.read_text(encoding="utf-8")
```

### 子 agent 也可以加载技能

对应 `tools/subagent.py`：

```python
_SUB_SYSTEM = (
    "你是一个子 agent，负责独立完成被委托的特定任务。\n"
    "使用可用工具（bash、read_file、write_file、load_skill）高效完成任务，\n"
    "遇到不熟悉的领域时先调用 load_skill 加载相关技能。\n"
    "完成后用简洁的文字总结结果。不要过度解释，直接行动。"
)

_SUB_TOOLS = [bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA, skill.SCHEMA]
```

### bash 重构后的结构

对应 `tools/bash.py`：

```python
COMMAND_TIMEOUT_SECONDS = 120
MAX_OUTPUT_LENGTH = 50_000

def _is_dangerous(command: str) -> bool:
    """检查命令是否包含危险子串。"""
    return any(bad in command for bad in _DANGEROUS)

def _truncate_output(text: str) -> str:
    """截断超长输出，防止撑爆上下文窗口。"""
    return text[:MAX_OUTPUT_LENGTH]
```

## 本次运行暴露的学习点

1. Skill 是延迟加载的知识，不是新的执行能力；真正执行仍靠已有工具。
2. `load_skill` 的价值在于把“什么时候需要什么知识”交给模型判断。
3. s05 与 s04 叠加后，必须明确主 agent 和子 agent 的上下文边界。
4. 真实运行能校正文档里的想当然预期，例如 `/tmp` 写入并不会被 `bash` 拦截。
5. 简单黑名单足够做教学安全防线，但不适合当成精准的命令语义分析器。

## 后续建议

- 修正 `examples/s05_demo_prompts.md` 中关于 `/tmp` 写入失败的预期。
- 统一 `skills/git.md` 与 `CLAUDE.md` 里的提交信息规范。
- 给 `tools/skill.py` 增加输出截断，避免大技能撑爆上下文。
- 考虑记录已加载技能，避免同一会话重复加载同一技能。
- 更新 `agents/s05_skills.py` 中对子 agent 工具集的描述，明确子 agent 已支持 `load_skill`。

## 一句话收获

> s05 让 agent 从“带着所有知识出门”变成“需要什么再查什么”；能力仍由工具提供，知识则通过 skill 按需进入上下文。
