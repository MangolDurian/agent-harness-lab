# s10: Team Protocols — 队友之间要有统一的沟通规矩

## 核心问题

s09 让队友能干活能通信，但消息太"随意"——没有结构化协调：
- 关机是直接发 `__shutdown__` 强杀线程，可能留下写了一半的文件
- 队友拿到任务就开干，高风险变更没有审批门控

两者结构一样：一方发带唯一 ID 的请求，另一方引用同一 ID 响应。

## 新增机制

### 1. ProtocolTracker（`tools/protocols.py`）

追踪两类协议请求，每个请求走 FSM：`pending → approved/rejected`。

```python
class ProtocolTracker:
    shutdown_requests: dict[str, dict]  # {req_id: {target, status}}
    plan_requests: dict[str, dict]      # {req_id: {from, plan, status}}
    lock: threading.Lock

    def request_shutdown(name) -> str       # Lead → Teammate
    def respond_shutdown(sender, req_id, approve, reason) -> str  # Teammate → Lead
    def submit_plan(sender, plan) -> str    # Teammate → Lead
    def review_plan(req_id, approve, feedback) -> str              # Lead → Teammate
    def list_requests() -> str
```

### 2. 两个协议

**Shutdown Protocol**（优雅关机替代 `__shutdown__` 强杀）：
```
Lead                         Teammate
  |--shutdown_request------->|
  | {req_id:"abc"}           |
  |<--shutdown_response------|
  | {req_id:"abc", approve}  |
```

**Plan Approval Protocol**（高风险操作审批门控）：
```
Teammate                     Lead
  |--plan_submit------------>|
  | {req_id:"xyz", plan}     |
  |<--plan_approval_response-|
  | {req_id:"xyz", approve}  |
```

### 3. 结构化消息（`team.py send()` 扩展）

`send()` 增加可选参数 `msg_type` 和 `metadata`，向后兼容：
```python
def send(self, sender, to, content, msg_type=None, metadata=None):
    msg = {"from": sender, "content": content}
    if msg_type: msg["type"] = msg_type
    if metadata: msg["metadata"] = metadata
```

inbox 格式化感知协议类型：`format_inbox_messages()` 检测 `type` 字段，
将 `shutdown_request`、`plan_approval_response` 等格式化为可读提示文本。

### 4. 队友扩展配置（`configure_teammate`）

`TeammateManager` 新增 `configure_teammate()` 方法，支持注入：
- `extra_tools`：追加到队友工具列表的 SCHEMA
- `handler_factories`：工厂函数 `{tool_name: factory(name) → handler}`
- `system_suffix`：追加到队友 system prompt 的文本

这样 `team.py` 不依赖 `protocols.py`，避免循环导入。

### 5. 优雅关机流程

1. Lead 调 `shutdown_request(name)` → 结构化消息发到队友 inbox
2. 队友 drain inbox 时检测到 `type=shutdown_request` → 格式化为协议提示
3. 队友调 `shutdown_response(approve=true)` → 响应消息发到 lead inbox + 设置 graceful exit flag
4. 队友线程检测到 flag → 跳过汇报、更新状态为 stopped、退出线程
5. Lead 下次 drain inbox 时看到响应消息

## 架构要点

- `core/loop.py` 一行不改
- `tools/team.py` 只做扩展（send 增加可选参数、configure_teammate、format_inbox_messages）
- `tools/protocols.py` 是独立新模块，通过 lazy import 获取 TeammateManager
- 队友的协议工具通过工厂函数绑定名字（`make_shutdown_response_handler(name)`）

## 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 协议实现位置 | 修改 agent_loop 内部 | 独立 `tools/protocols.py` 模块 + team.py send 扩展 |
| 队友工具注入 | 硬编码队友工具列表 | `configure_teammate()` 工厂模式，agent 层组装 |
| 关机方式 | 保留 `__shutdown__` 强杀 | 双轨：shutdown_request 握手优先，`__shutdown__` 兜底 |

## 机制边界：软门控 vs 硬门控

**计划审批是协议层软门控，不是工具层强制门控。**

队友是否先提交计划、是否等批准后再执行，主要靠 system prompt 和模型遵守协议。
当前代码没有在 `bash` / `write_file` 层阻断高风险操作——队友如果忽略协议直接执行，工具层不会拦。

这在 s10 是合理的，因为 s10 主题是"沟通规矩"，不是安全执行沙箱。
真正强制拦截高风险操作，需要后续阶段在工具层加 policy gate（比如 `write_file` 检查是否有对应 approved plan）。

**关机协议是工具层硬门控**——`shutdown_response(approve=true)` 后设置 graceful exit flag，
队友线程在 `_should_exit()` 检查时一定会退出，不依赖模型遵守。
