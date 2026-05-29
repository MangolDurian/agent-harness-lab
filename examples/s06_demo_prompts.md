# s06: Context Compact 验证 Prompt

> **背景**：micro_compact 每轮自动压缩旧 tool 输出，保持总 token 在
> 3 轮 × 单次输出 大小以内。auto_compact 是兜底机制，需要 token 估算
> 超过 `_AUTO_TOKEN_THRESHOLD`（默认 20000）才能触发。
> 关键限制：auto_compact 要求至少 5 个工具轮次（保留 3 + 当前 1 = 4，
> 至少还要 1 个可压缩），且分割点之前必须有 user 消息。
>
> **因此**：必须通过多次 REPL 输入来积累足够历史，单次查询内无论
> 调多少次工具，都只有一个 user 消息，无法产生有效分割点。

## Prompt 1：micro_compact 可观测

让 agent 连续读多个文件，观察旧的工具输出被自动压缩为占位符。

```
依次帮我读取以下文件，每个读完告诉我大概内容：
1. README.md
2. core/loop.py
3. core/llm.py
4. tools/bash.py
5. tools/read_file.py
```

**预期现象**：
- 前几个文件读取后，终端出现 `[micro_compact] 压缩了 N 条旧工具输出`
- 模型仍能正常回答，不会因为早期文件内容被压缩而出错

## Prompt 2：auto_compact 触发

通过多次 REPL 输入积累历史 + 大输出命令触发自动压缩。
**需要逐条输入**（每次等模型回复后再输下一条），这样每条都产生
独立的 user 消息，为 auto_compact 提供分割点。

```
（逐条输入以下命令）

输入1: 运行 python3 -c "print('A' * 50000)" 并告诉我输出长度
输入2: 再运行一次同样的命令
输入3: 再运行一次
输入4: 再运行一次
输入5: 再运行一次
```

**预期现象**：
- 第 4 或 5 次工具调用后出现 `[micro_compact] 压缩了 N 条旧工具输出`
- 随后出现 `[auto_compact] 触发压缩（token 超阈值，估算 ~XXXXX tokens）`
- 出现 `[auto_compact] 完成，XXXXX → XXXXX tokens`
- 对话继续正常进行

**原理**：每次 REPL 输入产生一条 user 消息 + 一轮 bash 工具调用。
5 次输入 = 5 条 user + 5 轮工具 = ~25K tokens（micro_compact 后仍超 20K 阈值）。
auto_compact 找到分割点（第 2 条 user 消息之前），摘要第 1 段对话。

## Prompt 3：compact 工具手动触发

手动调用 compact 工具强制触发 auto_compact（不受 token 阈值限制）。
需要先积累足够轮次（> 4 个工具轮次），否则 auto_compact 会跳过。

```
帮我依次读取这 6 个文件，每个读完告诉我文件名和大致内容：
1. README.md
2. core/loop.py
3. core/llm.py
4. tools/bash.py
5. tools/read_file.py
6. tools/write_file.py

读完全部后，调用 compact 工具压缩上下文。
```

**预期现象**：
- 出现 `[compact] 手动触发上下文压缩`
- 出现 `[auto_compact] 触发压缩（手动请求，估算 ~XXXX tokens）`
- 出现 `[auto_compact] 完成，XXXXX → XXXXX tokens`
- 模型收到压缩完成的反馈，继续正常工作

**备选方案**：如果单次查询的 6 次读取 + compact 不够
（因为只有 1 条 user 消息，auto_compact 可能无法分割），
改为分两步：
```
输入1: 帮我读 README.md、core/loop.py、core/llm.py 三个文件并告诉我内容
输入2: 再帮我读 tools/bash.py、tools/read_file.py、tools/write_file.py，然后调用 compact
```

## Prompt 4：压缩后继续工作

验证压缩不会破坏 agent 的正常工作能力。

```
（先执行 Prompt 2 或 3，等压缩触发后）
现在帮我读一下 agents/s06_context_compact.py 的前 20 行，告诉我这个文件做什么。
```

**预期现象**：
- agent 仍能正常调用工具、读取文件、回答问题
- 压缩只是腾空间，不影响后续工作
