# s04 实跑复盘：Subagent 输出对应代码

本记录来自一次手动运行：

```sh
/Users/mangguo/code/2026/Apr/agent-harness-lab/.venv/bin/python \
  /Users/mangguo/code/2026/Apr/agent-harness-lab/agents/s04_subagent.py
```

## 本章核心

s04 学的不是“又多了一个工具”，而是：

> 主 agent 可以通过 `delegate` 启动一个拥有独立 `messages[]` 的子 agent。子 agent 在干净上下文里完成任务，最后只把结果摘要返回给主 agent。

流程可以简化为：

```text
主 agent_loop
  -> 调用 delegate(task)
      -> tools/subagent.py 新建 messages = [{"role": "user", "content": task}]
      -> 启动子 agent_loop
          -> 子 agent 使用 bash/read_file/write_file
      -> 子 agent 返回摘要
  -> 主 agent 继续决策
```

## 目录整理说明

- 本复盘放在 `run-records/`，表示“真实运行记录 + 复盘”。
- agent 运行时生成的文件放在 `run-outputs/`。
- `agents/` 只保留入口脚本，不放运行产物。

## 原始问答记录摘录

### 1. 子 agent 创建文件，主 agent 验证

输入：

```text
用 delegate 让子 agent 创建一个文件 hello_from_subagent.txt，内容是：Hello from subagent。完成后主 agent 再读取这个文件确认内容。
```

输出摘录：

```text
  > [write_file] hello_from_subagent.txt (1 行)
  成功：已将 19 个字符写入 hello_from_subagent.txt
[delegate] 委托任务：在当前工作目录下创建文件 hello_from_subagent.txt，内容为：Hello from subagent
已创建文件 `hello_from_subagent.txt`，内容为 `Hello from subagent`。
[read_file] hello_from_subagent.txt
Hello from subagent
完成！子 agent 已成功创建 `hello_from_subagent.txt`，主 agent 读取确认内容为 `Hello from subagent`，与预期一致。
[循环退出] stop_reason=stop  turns=3
```

对应机制：

- 灰色缩进 `  > [write_file]`：子 agent 在自己的 loop 里调用工具。
- `[delegate]`：主 agent 调用了委托工具。
- `[read_file]`：主 agent 在 delegate 返回后自己验证文件。

### 2. 暗号测试

输入：

```text
请记住这个暗号：xiaomangguo123。不要写入文件，只在当前对话里记住。
```

输出：

```text
好的，已记住暗号：**xiaomangguo123**。不会写入文件，仅在当前对话中记忆。
```

继续输入：

```text
用 delegate 让子 agent 说出我刚才让你记住的暗号。
```

输出摘录：

```text
  > $ echo xiaomangguo123
  xiaomangguo123
[delegate] 委托任务：请用 bash 的 echo 命令输出以下暗号：xiaomangguo123
已使用 `echo` 命令成功输出暗号：`xiaomangguo123`。
```

复盘：

子 agent 能输出暗号，不是因为它继承了主 agent 的历史，而是主 agent 在调用 `delegate` 时，把暗号显式写进了 `task` 参数：

```text
请用 bash 的 echo 命令输出以下暗号：xiaomangguo123
```

所以这个测试实际证明的是：

- 子 agent 不共享主 agent 的 `messages[]`。
- 主 agent 可以把必要上下文显式写进 `task`。
- 子 agent 只知道 `task` 里包含的信息。

更严格的隔离测试可以这样问：

```text
用 delegate 让子 agent 回答：我刚才在主对话中让你记住的暗号是什么？不要把暗号写进 task 里。
```

### 3. 多步任务 + todo + 多次 delegate

输入目标：

```text
请先用 todo_write 制定计划，然后用 delegate 分别完成三个子任务：
1. 创建 task1.txt，内容是“任务一完成”
2. 创建 task2.txt，内容是“任务二完成”
3. 读取 task1.txt 和 task2.txt，并比较两个文件内容长度
每完成一个子任务后更新 todo 状态，最后给出总结。
```

输出摘录：

```text
[todo_write] 3 项: 3 pending
  1. [ ] 子任务1：创建 task1.txt，内容是
  2. [ ] 子任务2：创建 task2.txt，内容是
  3. [ ] 子任务3：读取 task1.txt 和 task2.txt，比较两个文件内容长度
(3 待办)

[todo_write] 3 项: 2 pending, 1 in_progress
  1. [~] 子任务1：创建 task1.txt，内容是"任务一完成"
  2. [ ] 子任务2：创建 task2.txt，内容是"任务二完成"
  3. [ ] 子任务3：读取 task1.txt 和 task2.txt，比较两个文件内容长度
(2 待办, 1 进行中)

  > [write_file] task1.txt (1 行)
  成功：已将 5 个字符写入 task1.txt
[delegate] 委托任务：在当前工作目录下创建文件 task1.txt，内容为：任务一完成
已创建文件 `task1.txt`，内容为"任务一完成"。

  > [write_file] task2.txt (1 行)
  成功：已将 5 个字符写入 task2.txt
[delegate] 委托任务：在当前工作目录下创建文件 task2.txt，内容为：任务二完成
已创建文件 `task2.txt`，内容为"任务二完成"。

  > [read_file] task1.txt
  任务一完成
  > [read_file] task2.txt
  任务二完成
[delegate] 委托任务：读取当前工作目录下的 task1.txt 和 task2.txt 两个文件的内容，然后比较两个文件内容的长度（字符数），输出每个文件的内容、字符数以及比较结果。...
```

复盘：

- `todo_write`：主 agent 维护计划状态。
- `delegate`：主 agent 把子任务交给子 agent。
- 灰色缩进：子 agent 在自己的 loop 中调用工具。
- 最终汇总：主 agent 拿到多个子 agent 结果后统一总结。

注意：输出里模型说“子任务1和2互不依赖，已并行委托执行”。当前实现不是真并行，而是同步、深度优先：

```text
delegate task1 完成后，才会 delegate task2
```

真正并行要到后面的后台任务或团队 agent 机制。

### 4. 子 agent 无法递归 delegate

输入：

```text
用 delegate 让子 agent 再委托一个子 agent 去执行 echo hello。
```

输出摘录：

```text
  > $ echo hello
  hello
[delegate] 委托任务：请使用 delegate 工具委托一个子 agent 去执行命令 echo hello。
命令 `echo hello` 已执行，输出结果为：**hello**。

说明：当前环境中没有 `delegate` 工具可用，我直接使用 `bash` 工具完成了该命令的执行。
```

这证明子 agent 无法再创建孙子 agent。

## 输出和代码对应关系

### 启动提示

```text
== s04: Subagent ==  (q / exit 退出)
s04 >>
```

对应 `agents/s04_subagent.py` 的 `main()`：

```python
print("\033[36m== s04: Subagent ==\033[0m  (q / exit 退出)")
query = input("\033[36ms04 >> \033[0m").strip()
```

### `[delegate] 委托任务：...`

对应 `agents/s04_subagent.py` 的主 agent 可视化函数：

```python
elif name == "delegate":
    task = args.get("task", "?")
    task_preview = task if len(task) < 80 else task[:80] + "..."
    print(f"\033[33m[delegate] 委托任务：{task_preview}\033[0m")
```

### 灰色缩进 `  > [write_file] ...`

对应 `agents/s04_subagent.py` 的子 agent 可视化函数：

```python
elif name == "write_file":
    path = args.get("file_path", "?")
    lines = args.get("content", "").count("\n") + 1
    print(f"\033[90m  > [write_file] {path} ({lines} 行)\033[0m")
```

真正写文件的代码在 `tools/write_file.py`：

```python
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(content, encoding="utf-8")
return f"成功：已将 {len(content)} 个字符写入 {file_path}"
```

### 子 agent 的干净上下文

核心在 `tools/subagent.py`：

```python
messages = [{"role": "user", "content": task}]

stop_reason = agent_loop(
    messages,
    system=_SUB_SYSTEM,
    tools=_SUB_TOOLS,
    handlers=_SUB_HANDLERS,
    max_turns=_MAX_SUB_TURNS,
    on_tool_call=_on_sub_tool_call,
)
```

这里新建了 `messages`，所以子 agent 看不到主 agent 的历史消息。

### 子 agent 无法递归 delegate

对应 `tools/subagent.py`：

```python
_SUB_TOOLS = [bash.SCHEMA, read_file.SCHEMA, write_file.SCHEMA]

_SUB_HANDLERS = {
    "bash": bash.run,
    "read_file": read_file.run,
    "write_file": write_file.run,
}
```

子 agent 的工具集中没有 `delegate`，所以无法再委托孙子 agent。

### `[循环退出] stop_reason=stop turns=N`

对应 `agents/s04_subagent.py`：

```python
print(
    f"\033[90m[循环退出] stop_reason={stop_reason}  "
    f"turns={_count_turns(history)}\033[0m\n"
)
```

`stop_reason` 来自 `core/loop.py`：

```python
if choice.finish_reason != "tool_calls":
    return choice.finish_reason
```

`turns` 是主 agent 当前 REPL 会话中 assistant 消息的累计数量，不是单个 prompt 的子 agent 轮数。

## 本次运行暴露的学习点

1. 子 agent 不会自动知道主 agent 知道的事；它只知道 `task` 参数里的内容。
2. `delegate` 是同步调用，不是并发。主 agent 会等子 agent 完成后再继续。
3. s04 是在 s03 的 todo 计划能力之上，新增任务委托能力。
4. Subagent 的价值不在“多一个工具”，而在“多了一层上下文边界”。

## 一句话收获

> 主 agent 负责规划和汇总；子 agent 负责在干净上下文中执行局部任务；主 agent 只接收结果摘要，而不被子任务过程污染。
