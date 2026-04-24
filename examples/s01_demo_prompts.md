# s01 阶段成果验证清单

跑 `python agents/s01_agent_loop.py`，依次输入下面 4 个 prompt，对照预期现象。

---

## ✅ 1. 单工具 · 单轮

**Prompt**

```
Create a file hello.py that prints "Hello, s01!", then run it.
```

**预期**

- 至少 2 次 `$ ...` 黄字（一次写文件，一次 `python hello.py`）
- 最后绿字出现 `Hello, s01!` 或一句简短总结
- `[loop exit] stop_reason=end_turn turns=N`，N ≥ 2

**证明的机制** —— 循环确实在跑：模型调工具 → harness 执行 → 结果回灌 → 模型再决策。

---

## ✅ 2. 多步骤 · 连续多轮工具

**Prompt**

```
Count how many python files are in this directory, tell me total lines across all of them.
```

**预期**

- 至少 2~3 次 `$ ...`（find / wc 之类）
- `turns` 明显 > 1
- 绿字给出一个具体数字

**证明的机制** —— stop_reason 驱动的循环会按模型的节奏自动延续，代码不需要写"步骤编排"。

---

## ✅ 3. 并发工具调用 · 单轮多个 tool_use

**Prompt**

```
In parallel, tell me: current git branch (if any), python version, and the OS name.
```

**预期**

- 很可能在**一次** assistant turn 里就输出 3 行 `$ ...`（同一轮并发调用）
- 没有 400 错误

**证明的机制** —— 你的代码正确处理了"一个 assistant turn 里多个 tool_use block"，
每个 tool_use_id 都配对了一个 tool_result，在同一个 user 消息里一起交回去。
**这是原版代码里最容易踩的坑，过了说明 dispatch 循环写对了。**

---

## ✅ 4. 不调工具 · 直接 end_turn

**Prompt**

```
In one sentence, what does stop_reason == "tool_use" mean?
```

**预期**

- **没有**黄字 `$ ...`
- 只有绿字一句话
- `stop_reason=end_turn turns=1`

**证明的机制** —— 模型不想调工具时，stop_reason 分支立刻退出循环，
没有无谓的轮次，代码没替模型做决策。

---

## 结业条件

4 个都 ✅ → s01 通过，可以进入 s02。

如果有任何一个失败：
- 1/2 失败多半是 prompt 写得不够具体，或 API key/模型 ID 配置问题
- 3 失败要回去检查 `core/loop.py` 里 tool_use 的循环和 results 的收集
- 4 失败要检查 `stop_reason != "tool_use"` 的退出分支
