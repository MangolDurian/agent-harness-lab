# s04 验证清单

运行 `python agents/s04_subagent.py`，依次执行以下测试 prompt。

## 1. 基本委托

**Prompt：**
```
用 delegate 让子 agent 执行：创建一个文件 hello.txt，内容是 Hello from subagent。
```

**预期现象：**
- 主 agent 调用 `delegate`，显示 `[delegate] 委托任务：...`
- 子 agent 的工具调用以灰色缩进 `  >` 显示（`write_file`）
- 子 agent 完成后，结果返回给主 agent
- 最终文件被创建

## 2. 任务隔离验证

**Prompt（先执行）：**
```
请记住这个密码：xiaomangguo123
```

**Prompt（再执行）：**
```
用 delegate 让子 agent 说出我刚才让你记住的密码。
```

**预期现象：**
- 子 agent 不知道密码（因为它是全新上下文）
- 子 agent 会回复类似"我不知道你之前说了什么"
- 证明子 agent 的上下文确实是隔离的

## 3. 多步委托

**Prompt：**
```
先用 todo_write 规划以下任务，然后逐项用 delegate 委托给子 agent 执行：
1）创建文件 task1.txt 内容是"任务一完成"
2）创建文件 task2.txt 内容是"任务二完成"
3）读取两个文件并比较内容长度
```

**预期现象：**
- 主 agent 先调 todo_write 做计划
- 然后逐项调 delegate，每次都有子 agent 的灰色缩进输出
- 每完成一项，主 agent 更新 todo 状态
- 最终汇总结果

## 4. 子 agent 无法递归

**Prompt：**
```
用 delegate 让子 agent 再委托一个子 agent 去执行 echo hello。
```

**预期现象：**
- 子 agent 没有 `delegate` 工具可用
- 子 agent 会直接用 bash 执行 `echo hello`，或者报告无法委托
- 证明防递归机制生效
