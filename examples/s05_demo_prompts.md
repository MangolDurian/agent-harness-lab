# s05 验证清单

运行 `python agents/s05_skills.py`，依次执行以下测试 prompt。

## 1. 加载指定技能

**Prompt：**
```
加载 git 技能，查看当前 git 状态，并根据技能规范拟定一个中文提交信息。不要执行 git add 或 git commit。
```

**预期现象：**
- 模型先调用 `load_skill("git")`
- 输出显示 `[load_skill] 加载技能：git`
- 模型按照 git.md 中的规范查看状态、拟定提交信息（不执行真实提交）

## 2. 技能引导触发

**Prompt：**
```
帮我排查一下为什么 echo 'hello' > /tmp/test.txt 这个命令写入失败了。
```

**预期现象：**
- 模型调用 `load_skill("debug")` 加载调试技能
- 按照 debug.md 中的排查流程执行（确认问题、缩小范围、验证假设）
- 最终发现是路径安全策略拦截（/tmp 在工作目录外）

## 3. 未知技能返回列表

**Prompt：**
```
加载一个叫做 python 的技能。
```

**预期现象：**
- 返回"未知技能 'python'"
- 同时列出可用技能列表：git、debug、refactor
- 模型可能会从中选择一个加载

## 4. 技能 + 委托组合

**Prompt：**
```
加载 refactor 技能，然后把 tools/bash.py 按照重构指南中的原则优化一下。
用 delegate 委托子 agent 执行具体的代码修改，在 task 中写清楚重构原则。
```

**预期现象：**
- 模型先调 `load_skill("refactor")` 获取重构知识
- 然后 delegate 委托子 agent，**把重构要点写进 task 参数**（因为子 agent 是干净上下文）
- 子 agent 按照传入的原则执行修改
- 或者：子 agent 自己调用 `load_skill("refactor")` 加载技能后再执行
- 展示 s04 的子 agent 缩进可视化 + s05 的技能加载
