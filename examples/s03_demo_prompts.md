# s03 验证清单

运行 `python agents/s03_todo.py`，依次执行以下测试 prompt。

## 1. 基本 todo 操作

**Prompt：**
```
Create a todo list with 3 items: 1) read README.md, 2) list current directory, 3) say hello. Start with all pending.
```

**预期现象：**
- 模型调用 `todo_write`，传入 3 项 pending 的任务
- 输出显示 `[todo_write] 3 items: 3 pending`
- 格式化的 todo 列表带有 `[ ]` 图标和自动编号

## 2. 任务驱动执行

**Prompt：**
```
Create a file called test_plan.txt with three lines: line1, line2, line3. Make a plan first, then execute step by step.
```

**预期现象：**
- 模型先调 `todo_write` 创建计划（创建文件 → 验证内容）
- 然后逐步执行，每次将当前任务标记为 `in_progress`/`completed`
- `[todo_write]` 可视化显示状态变化

## 3. Nag 触发

**Prompt：**
```
Run these commands one by one: echo step1, echo step2, echo step3, echo step4, echo step5. Do NOT use todo_write.
```

**预期现象：**
- 前 3 次工具调用正常输出 bash 结果
- 第 4 次工具调用起，输出末尾出现 `[REMINDER] You haven't updated your todo list in N tool calls.`
- 模型可能会在 nag 出现后主动调 `todo_write`

## 4. Nag 重置

**Prompt（连续对话，接上一个 prompt 后）：**
```
Now create a todo list tracking what you just did, then run echo done.
```

**预期现象：**
- 调用 `todo_write` 后，nag 计数器归零
- 后续的 bash 调用不再出现 `[REMINDER]` 提醒（除非再连续 3 次工具调用不调 todo_write）
