# s08: Background Tasks 验证 Prompt

> **背景**：s08 在 s07 基础上增加后台任务机制。bash 工具新增 `run_in_background` 参数，
> 慢命令丢后台线程执行，agent 立即继续干别的，后台完成后再把结果带回上下文。
> 四个关键机制：handler wrapper collect()、post-loop flush、超时轮询（10 秒上限）、background_status 工具。
>
> 运行方式：`python agents/s08_background.py`
> 建议按顺序跑，重点看「通知到底在哪一步、靠哪个机制冒出来」。

---

## Prompt 1：普通命令（不后台）

验证默认行为与 s07 完全一致，不受后台机制影响。

```
echo hello world
```

**预期现象**：
- 正常执行 `echo hello world`，输出 `hello world`
- 不带 `[background]` 标记，行为与 s07 完全一致

---

## Prompt 2：后台命令立即返回

验证 `run_in_background=true` 时命令不阻塞。

```
运行 sleep 3 && echo "background done" 这个命令，用后台模式（run_in_background=true）
```

**预期现象**：
- 命令显示 `[background]` 标记
- 立即返回「后台任务 bg_1 已启动」，**不阻塞 3 秒**
- 3 秒后任务完成（通知由后续工具调用、post-loop flush 或超时轮询带出来——见后面的 prompt）

---

## Prompt 3：后台 + 中间真占时间的命令，通知在后续工具调用中冒出来

验证 handler wrapper 的 collect() 在后续工具调用时把后台通知带出来。

```
先用后台模式运行 sleep 3 && echo "bg task finished"，然后连续运行 4 次「sleep 1 && echo waiting」，每次都单独调用 bash
```

**预期现象**：
- sleep 3 在后台启动
- agent 连续执行 4 次 `sleep 1 && echo waiting`，每次约 1 秒
- 后台任务在第 3 秒前后完成，**第 3 或第 4 次** `sleep 1 && echo waiting` 的工具输出**前面**会出现 `[后台任务 bg_1 完成] ...` 通知
- 说明：如果中间用纯 `echo`（瞬间返回），4 次会在 1 秒内跑完，通知来不及在工具输出里出现，只能靠 post-loop 兜底——这条专门用 sleep 1 把时间拉开

---

## Prompt 4：不带 run_in_background 的慢命令，正常阻塞

验证不设 `run_in_background` 时慢命令仍阻塞（默认行为不变）。

```
运行 sleep 2 && echo "blocking done"
```

**预期现象**：
- 命令正常阻塞约 2 秒
- 行为与 s07 完全一致，证明默认行为不受后台机制影响

---

## Prompt 5：「跑完告诉我」+ 不再开口，超时轮询兜底

验证 post-loop flush + 超时轮询：全程不需要用户再开口。

```
用后台模式运行 sleep 5 && echo "install done"，跑完了告诉我结果，我不会再发消息
```

**预期现象**：
- 后台任务启动，模型回一句「已启动，完成后告诉你」就停止调工具，`agent_loop` 退出
- 退出时 sleep 5 还在跑 → `collect()` 为空、`has_running()` 为真 → 进入**超时轮询**
- 约 5 秒后任务收尾，轮询 collect 到结果，注入 user 消息再跑一轮，模型给出最终确认
- CLI 打印 `[后台任务完成，通知模型]`；现象是「模型答完后停顿约 5 秒才回到 `s08 >>` 提示符」
- **关键**：全程不需要用户再开口，这是超时轮询的核心价值

---

## Prompt 6：「装好了吗」两轮对话，background_status 主动查询

验证模型在用户追问时调用 `background_status` 而不是凭记忆瞎答。

第一轮：

```
用后台模式运行 sleep 8 && echo "torch installed"
```

第二轮（紧接着，趁 8 秒还没到时输入）：

```
装好了吗？
```

**预期现象**：
- 第一轮：后台任务启动，立即返回
- 第二轮：模型**调用 `background_status`** 确认，而不是凭记忆回答
- 若还在跑：看到 `bg_1: 运行中 - sleep 8 && echo "torch installed"`
- 若刚好已完成：wrapper 的 collect() 把完成通知拼到 `background_status` 输出前面
- **关键**：验证 SYSTEM 提示词里「用户问装好了吗，用 background_status 确认」是否生效

---

## Prompt 7：多个后台任务

验证多个后台任务并行，通知批量或分批带出来。

```
同时用后台模式运行两个命令：sleep 2 && echo "task A done" 和 sleep 3 && echo "task B done"
```

**预期现象**：
- 两个后台任务都启动，返回两个 bg_id（bg_1 和 bg_2）
- 2~3 秒后两个任务先后完成
- 通知通过 post-loop flush / 超时轮询带出来；可能分两轮 flush（A 先完成注入一轮，B 再完成再注入一轮）

---

## Prompt 8：（边界）超过 10 秒的任务，轮询放弃，通知顺延

验证 10 秒上限边界：超过上限的任务，post-loop 兜不住。

第一轮：

```
用后台模式运行 sleep 15 && echo "very slow done"，跑完告诉我
```

第二轮（等过 15 秒后再输入）：

```
好了吗？
```

**预期现象**：
- 第一轮：任务启动；模型停止后进入超时轮询，但 15 秒 > 10 秒上限，**轮询等不到**，10 秒后放弃 break
- 第二轮：此时 sleep 15 早已完成，模型调 `background_status` 或任意工具时，wrapper 的 collect() 把完成通知带出来
- **关键**：这条验证 `docs/s08-notes.md` 里写的「10 秒上限」边界——超过上限的任务需要下一轮交互才能拿到结果，是刻意的工程取舍，不是 bug
