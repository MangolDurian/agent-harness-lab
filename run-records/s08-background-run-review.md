# s08 Background Tasks 实跑复盘

> 运行环境：**Web 前端**（`web/server.py` + `web/index.html`，stage=s08），按 `examples/s08_demo_prompts.md` 8 条 prompt 依次输入。
> 判定依据：记录里 `后台任务完成，通知模型处理` 是 web 的 `system_message` 文案（CLI 为 `[后台任务完成，通知模型]`），`BG` 徽标与 `[bg]` 后缀均为 `web/index.html` 渲染。
> 关注点：后台通知到底靠哪个机制、在哪一步冒出来。

---

## 逐条记录

### 1. 普通命令（不后台）

**输入**：`echo hello world`

```
$ echo hello world
hello world
→ hello world 已输出
```

**判定**：✅ 与 s07 一致，无 `[background]` 标记。

---

### 2. 后台命令：立即返回 + post-loop flush

**输入**：`运行 sleep 3 && echo "background done"，用后台模式`

```
$ sleep 3 && echo "background done" [bg]
后台任务 bg_1 已启动…
后台任务完成，通知模型处理          ← post-loop flush / 超时轮询
→ 后台任务已完成，输出 background done ✅
```

**判定**：✅ 立即返回不阻塞；模型停止后，post-loop 主动把结果捞回来并再跑一轮确认。这是「模型只回文字就停」场景的兜底，符合预期。

---

### 3. 后台 + 中间真占时间的命令：通知在工具调用中冒出

**输入**：`后台跑 sleep 3 && echo "bg task finished"，然后连续 4 次 sleep 1 && echo waiting`

```
$ sleep 3 && echo "bg task finished" [bg]   → bg_2 已启动
$ sleep 1 && echo waiting → waiting
$ sleep 1 && echo waiting → waiting  [提醒] 连续 3 次未更新任务列表…
$ sleep 1 && echo waiting → waiting  [提醒] 连续 4 次未更新任务列表…
$ sleep 1 && echo waiting →
   [后台任务 bg_2 完成] sleep 3 && echo "bg task finished"
   bg task finished
   waiting  [提醒] 连续 5 次未更新任务列表…
→ 全部完成：bg_2 输出 bg task finished ✅，4 次前台各输出 waiting ✅
```

**判定**：✅ 核心机制验证成功——后台任务在第 4 次 `sleep 1` 完成，`collect()` 把 `[后台任务 bg_2 完成]` 拼到了那次工具输出**前面**。这正是「中间命令真占时间」才能演示出的效果（对比纯 echo 会太快）。

**副观察**：⚠️ nag 提醒在第 3/4/5 次连续触发。这几次都是纯 bash 操作、本不需要任务列表，nag 仍照常计数，输出里混进大段提醒文本。属 s03 既有行为，但在后台演示里显得很吵。

---

### 4. 不带 run_in_background 的慢命令：正常阻塞

**输入**：`运行 sleep 2 && echo "blocking done"`

```
$ sleep 2 && echo "blocking done"
blocking done
→ blocking done ✅
```

**判定**：✅ 默认行为不受影响，正常阻塞约 2 秒。

---

### 5. 「跑完告诉我，我不再发消息」——模型自己用前台 sleep 堵住等

**输入**：`后台跑 sleep 5 && echo "install done"，跑完了告诉我，我不会再发消息`

```
$ sleep 5 && echo "install done" [bg]   → bg_3 已启动
$ sleep 6                                ← 模型主动发的前台 sleep！
   [后台任务 bg_3 完成] sleep 5 && echo "install done"
   install done
   （sleep 6 自身无输出）
→ 后台任务已完成，输出 install done ✅
```

**判定**：✅ 结果正确，但**走的路径出乎预期**。我设计这条是想验证「超时轮询」兜底，但模型没有"回一句话就停"，而是**主动发了一个前台 `sleep 6` 把自己堵住**，等后台 `sleep 5` 跑完后，靠 `sleep 6` 这次工具调用的 `collect()` 前缀把通知带出来。

**关键发现**：模型把"等后台跑完"翻译成了"我自己睡一会儿"。超时轮询那条新分支**这一轮根本没被触发**，因为模型用前台 sleep 抢先把通知接出来了。

---

### 6. 「装好了吗」两轮对话 + background_status

**第一轮输入**：`后台跑 sleep 8 && echo "torch installed"`

```
$ sleep 8 && echo "torch installed" [bg]   → bg_4 已启动
后台任务完成，通知模型处理                  ← 第一轮就被 post-loop 捞走了
→ 后台任务已完成，输出 torch installed ✅
```

**第二轮输入**：`装好了吗？`

```
[background_status] check background tasks
没有正在运行的后台任务。
→ 已经装好了！bg_4 早已完成，输出 torch installed ✅
```

**判定**：⚠️ 结果对，但**没测到我想测的场景**，根因是 Web 前端的交互模型。本想让用户"趁 8 秒没到时"问"装好了吗"，看模型用 `background_status` 查到「运行中」。但在 Web 端这个窗口被**双重叠加**吃掉了：

1. **前端严格一问一答**：`web/index.html` 的 `sendMessage()` 在 `isProcessing` 为真时直接 return、发送按钮 `disabled`；`isProcessing` 只在收到 `processing_end` 才解除。所以第一轮没结束，"装好了吗"根本发不出去。
2. **post-loop 超时轮询撑着第一轮不结束**：sleep 8 < 10 秒上限，`_run_agent_in_thread` 的轮询会一直等到 bg_4 跑完（约 8 秒）才 collect、注入、再确认，然后才发 `processing_end`。

两者叠加 → 等用户能打字时，任务早已完成且通知已注入，`background_status` 只能回「没有正在运行的」。

**关键发现**：**这不是 `background_status` 坏了，是 Web 端压根没给"运行中"留提问窗口。** 对 ≤10 秒的后台任务，第一轮要等任务跑完才 `processing_end`，用户全程被锁输入。`background_status` 的「运行中」分支要想被看到，需要同时满足：任务 >10 秒（轮询超时放弃、第一轮在 10 秒就结束）**且** 模型没用前台 sleep 自堵（见发现 1）——例如后台跑 sleep 12、模型回完即停，第一轮在 10 秒结束后还剩约 2 秒窗口，此时问"装好了吗"才能查到运行中。窗口很窄但存在。

---

### 7. 多个后台任务

**输入**：`同时后台跑 sleep 2 && echo "task A done" 和 sleep 3 && echo "task B done"`

```
$ sleep 2 && echo "task A done" [bg]   → bg_5 已启动
$ sleep 3 && echo "task B done" [bg]   → bg_6 已启动
后台任务完成，通知模型处理
→ 两个都完成：bg_5 task A done ✅，bg_6 task B done ✅
```

**判定**：✅ 两任务并发启动，post-loop 轮询等到都收尾（has_running 转 false）后一次性 collect 到两条，模型同轮报告 A、B。

---

### 8.（边界）超过 10 秒的任务：模型又用前台 sleep 堵住

**第一轮输入**：`后台跑 sleep 15 && echo "very slow done"，跑完告诉我`

```
$ sleep 15 && echo "very slow done" [bg]   → bg_7 已启动
$ sleep 16                                  ← 模型又发前台 sleep！
（记录到此截断，未见最终确认）
```

**判定**：⚠️ 边界没测成。本想验证「15 秒 > 10 秒上限 → 轮询放弃 → 通知顺延到下一轮」。但模型再次**主动发前台 `sleep 16`** 把自己堵住，等后台 `sleep 15` 完成后用 `sleep 16` 这次调用的 collect 前缀接结果。于是「10 秒上限兜不住」这个边界又被模型的 sleep 策略绕过了。

**关键发现**：这是第 5 条同款行为的复现——只要任务给了明确的"跑完告诉我"，模型就倾向于**用前台 sleep 自己等**，而不是依赖 post-loop 轮询或 background_status。

---

## 关键发现汇总

### 1. 模型偏好「前台 sleep 自堵」而非依赖兜底机制（最重要）

第 5、8 两条，模型都主动发 `sleep N`（N 略大于后台任务时长）把自己堵住，靠下一次工具调用的 `collect()` 前缀接通知。后果：

- 我精心加的**超时轮询**这条新分支，在"跑完告诉我"场景里**反而没被触发**——模型抢在前面用前台 sleep 把通知接走了。
- 这某种程度上**消解了后台执行的初衷**（本来是为了"别阻塞"，模型却主动选择阻塞）。但在"用户说跑完告诉我、我不再发消息"这种没有别的事可做的场景下，模型这么做其实是合理的——它没有更好的"等待"原语，sleep 是它能想到的最直接的"挂起自己"方式。
- 启示：如果想让模型走 background_status / post-loop 这条路，SYSTEM 里需要更明确地引导（比如"不要用前台 sleep 等待后台任务，直接结束这一轮，系统会在完成后通知你"）。这是个 prompt engineering 问题，不是代码 bug。

### 2. Web 前端「一问一答」+ 超时轮询，叠加吃掉「运行中」提问窗口

第 6 条暴露的真正根因是 Web 端的交互模型，不是 `background_status` 本身：

- 前端 `isProcessing` 期间锁输入（`sendMessage()` 直接 return + 按钮 disabled），第二条消息必须等 `processing_end`。
- 而 `processing_end` 要等 `_run_agent_in_thread` 整轮跑完，**含 post-loop 超时轮询**——对 ≤10 秒任务，轮询会一直等到任务完成才结束第一轮。

两者叠加 → 用户在 ≤10 秒任务期间**完全没有**发"装好了吗"的窗口。这和 `docs/s08-notes.md` 写的「轮询阻塞主线程 / `processing_end` 延迟最多 10 秒」是同一回事，这次实跑给了具体证据，并补充了前端交互层的根因。要真正演示 `background_status` 的「运行中」分支，需任务 >10 秒 + 模型不自堵（见发现 1），第一轮在 10 秒超时结束后才有窄窗口。

### 3. nag 在纯后台/bash 演示里很吵

第 3 条连续 3/4/5 次触发 nag 提醒，混入大段无关文本。后台任务演示通常不涉及任务列表，nag 照常计数。属 s03 既有设计，但值得记一笔：演示后台机制时，nag 噪声会干扰对"通知前缀"的观察。

### 4. 真正被实跑验证到的机制

| 机制 | 验证情况 |
|---|---|
| 立即返回不阻塞 | ✅ 全部后台命令都立即返回 bg_id |
| collect() 输出前缀注入 | ✅ 第 3 条第 4 次 sleep 输出前出现完成通知 |
| post-loop flush / 超时轮询 | ✅ 第 2、6、7 条（模型停止后系统主动捞回） |
| background_status 主动查询 | ✅ 调用成功，但只测到「无运行中」分支（见发现 2） |
| 多任务并发 | ✅ 第 7 条 bg_5/bg_6 并发 |
| 超时轮询 vs 10 秒上限 | ⚠️ 未测到（被模型前台 sleep 绕过，见发现 1） |

---

## 结论

s08 的后台机制功能上**全部跑通、结果全对**，没有崩溃或数据错乱。但这次实跑最大的价值不在"验证通过"，而在两个**非代码层面的发现**：

1. **模型不爱用兜底机制**：给了明确的"跑完告诉我"，模型宁愿用前台 `sleep` 自堵也不走 post-loop 轮询/background_status。要纠正得改 SYSTEM 引导，而非改代码。
2. **Web 前端"一问一答" + 超时轮询，叠加吃掉了"运行中"提问窗口**：≤10 秒任务期间用户被锁输入、根本发不出"装好了吗"，导致 `background_status` 的运行中分支看不到。这是前端交互层 + 轮询阻塞的合并效应，不是 `background_status` 的问题。

后续若要继续打磨，优先级是 SYSTEM 提示词的引导（让模型信任异步通知、别用前台 sleep 等待），其次才是把轮询阻塞改成非阻塞/事件驱动。两者都属于"可改进"，不影响当前结业。
