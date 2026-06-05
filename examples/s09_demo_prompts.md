# s09 Demo Prompts

验证 s09 Agent Teams 的功能。每条 prompt 应跑出预期现象。

## 1. spawn 创建队友 + 完成后汇报

**Prompt:**
```
创建一个队友 quick（coder），让她写一个 hello world 程序到 run-outputs/s09/hello.py。
等她完成后告诉我结果。
```

**预期：**
- spawn 创建 quick，显示"已创建并开始工作"
- quick 在后台独立工作（终端会打印 `[quick] 开始工作...`）
- quick 完成后通过 inbox 汇报 lead
- REPL 等待轮询会等到 quick 的消息，通知模型处理
- lead 最终汇报 quick 的结果

## 2. team_status 查看状态

**Prompt:**
```
创建一个队友 worker（coder），让她执行 echo hello。
然后查看团队状态。
```

**预期：**
- team_status() 显示 worker 的状态（working 或 idle，取决于执行速度）
- 状态格式：`=== 团队状态 ===` + 各队友信息

## 3. 并发 spawn 多个队友

**Prompt:**
```
帮我创建两个队友并发干活：
1. alice（coder）：写一个 Python 函数计算斐波那契数列，保存到 run-outputs/s09/fib.py
2. bob（coder）：写一个 Python 函数计算阶乘，保存到 run-outputs/s09/factorial.py
创建完之后查看团队状态。
```

**预期：**
- 连续两次 spawn，两个队友并发工作
- team_status 显示两个 working（如果查看得够快）
- 两个队友先后完成，汇报 lead
- lead 收到两条队友消息

## 4. send 给空闲队友发新任务（验证持久化）

**Prompt:**
```
先创建一个队友 alice（coder），让她写一个加法函数到 run-outputs/s09/add.py。
等她完成后，再给 alice 发一条消息让她再写一个减法函数到 run-outputs/s09/sub.py。
```

**预期：**
- alice 完成第一个任务后进入 idle
- send 给 alice 发新任务，alice 被唤醒进入 working
- alice 完成第二个任务后再次汇报 lead

## 5. broadcast 广播消息

**Prompt:**
```
创建两个队友 coder（coder）和 tester（tester）。
然后广播一条消息："项目编码规范：所有函数名用 snake_case。"
查看团队状态确认广播已发送。
```

**预期：**
- broadcast 一次性给两个队友发消息
- 两个队友都能在 inbox 中收到广播
- 返回 "消息已广播给 N 人"

## 6. 名字校验（防护验证）

**Prompt:**
```
创建一个名为 lead 的队友。
```

**预期：**
- 返回错误："错误：'lead' 是保留名，不能用作队友名"

## 7. send 校验（防护验证）

**Prompt:**
```
给一个叫 nobody 的队友发消息。
```

**预期：**
- 返回错误："发送失败：接收者 'nobody' 不存在于团队中"
