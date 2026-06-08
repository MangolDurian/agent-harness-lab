# s10: Team Protocols 验证清单

## 运行方式

```bash
source .venv/bin/activate
python agents/s10_team_protocols.py
```

建议先清理上次运行残留：`rm -rf .team`（`.team/` 存放花名册和 inbox，不清理可能残留已停队友）。

## 验证 1：优雅关机协议

```
请创建一个叫 alice 的 coder 队友，让她在 run-outputs/s10/ 目录下创建 hello.txt 并写入 Hello from Alice。等她完成后再请求她优雅关机。
```

**预期**：lead 调用 spawn 创建 alice，alice 完成后 lead 调用 shutdown_request，alice 响应 shutdown_response(approve=true) 后优雅退出。lead 收到关机响应通知。

**检查**：alice 关机后 `team_status` 应显示 alice 状态为 stopped。

## 验证 2：关机请求发给不存在的队友

```
请请求一个叫 ghost 的队友关机。
```

**预期**：shutdown_request 返回错误"ghost 不存在于团队中"，`list_requests()` 不会留下 pending 请求。

## 验证 3：计划审批协议（拒绝后调整）

```
请创建一个叫 bob 的 coder 队友，给他分配任务：在 run-outputs/s10/ 目录下创建一些 .tmp 文件然后删除它们。告诉他删除前必须先用 plan_submit 提交计划等待审批。当 bob 提交计划时，先拒绝，告诉他只删除 .tmp 文件不要创建。
```

**预期**：bob 提交 plan_submit，lead 用 plan_review(approve=false) 拒绝并给出反馈。bob 收到拒绝后调整方案。

## 验证 4：计划审批协议（批准后执行）

```
请创建一个叫 charlie 的 coder 队友，让他创建 run-outputs/s10/notes.md 文件，写一些随机笔记。要求他先提交计划等审批。等他提交后批准他的计划。
```

**预期**：charlie 提交计划，lead 用 plan_review(approve=true) 批准，charlie 收到包含原始计划的批准消息后执行。

## 验证 5：查看协议请求状态

```
请查看所有协议请求的状态。
```

**预期**：list_requests 返回所有协议请求（关机 + 计划），显示 req_id、目标/来源、状态。

## 验证 6：普通通信仍然正常

```
请创建一个叫 dave 的 coder 队友让他等待通知，然后发消息给他：请在 run-outputs/s10/ 创建 dave.txt。
```

**预期**：普通 send 通信不受协议影响，向后兼容。

## 验证 7：并发多队友 + 混合协议

```
请同时创建两个队友：alice（coder）去写 run-outputs/s10/a.txt，bob（coder）去检查 run-outputs/s10/ 目录的内容。等他们都空闲后，优雅关机 alice。
```

**预期**：多个队友并发工作，协议和普通消息混用不冲突。shutdown_request 只关 alice，bob 不受影响。

## 机制边界说明

计划审批（plan_submit / plan_review）是**协议层软门控**：队友是否遵守取决于 system prompt，工具层不强制拦截。
关机协议（shutdown_request / shutdown_response）是**工具层硬门控**：approve=true 后 graceful exit flag 一定会让队友线程退出。
