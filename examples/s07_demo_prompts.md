# s07: Task System 验证 Prompt

> **背景**：s07 用 tools/task.py（持久化、增量、父子层级）替代 tools/todo.py（内存、全量替换、扁平）。
> 三个工具：task_create / task_update / task_list。
> 运行前先删除 `data/tasks.json`（如果存在），确保从干净状态开始。

## Prompt 1：创建带子任务的分层计划

验证 task_create 的批量创建和 parent_id 父子层级。

```
帮我规划一个"搭建 Web API"的项目，要求：
1. 先创建根任务"搭建 Web API"
2. 然后创建 3 个子任务，分别挂在根任务下面：
   - 设计数据库 schema
   - 实现 API 端点
   - 编写测试
3. 所有子任务初始状态为 pending
```

**预期现象**：
- 模型调用 task_create 一次（或分两次：先创建根任务获取 ID，再创建子任务）
- 终端输出树形格式化，根任务显示 `1. [ ] 搭建 Web API`，子任务显示 `1.1. [ ] ...`
- `data/tasks.json` 文件被创建，内容为 JSON 格式的任务数据

## Prompt 2：逐步更新状态

验证 task_update 的增量更新和全局单 in_progress 约束。

```
开始执行项目计划：
1. 把"设计数据库 schema"标记为 in_progress
2. 运行 ls data/ 看看当前目录结构
3. 完成后把"设计数据库 schema"标记为 completed
4. 把"实现 API 端点"标记为 in_progress
```

**预期现象**：
- 模型用 task_update 将任务标记为 in_progress / completed
- 每次更新后输出新的格式化任务树
- 同一时刻只有一个 in_progress 任务

## Prompt 3：查看任务

验证 task_list 的状态筛选功能。

```
用 task_list 查看所有已完成的任务，然后再查看所有 pending 的任务。
```

**预期现象**：
- 模型调用 task_list(status="completed") 返回已完成任务
- 模型调用 task_list(status="pending") 返回待办任务
- 两次筛选结果不重叠

## Prompt 4：退出重启后恢复

验证持久化：进程退出后任务不丢失。

```
（执行 Prompt 1-3 后，输入 q 或 exit 退出 agent）

重新启动：
python agents/s07_task_system.py

输入：
调用 task_list 看看当前有哪些任务
```

**预期现象**：
- 重启后 task_list 能读取上次保存的所有任务
- 任务状态、父子关系、文本内容都完整保留
- `data/tasks.json` 文件存在且内容与上次一致

## Prompt 5：Nag 提醒

验证连续工具调用不更新任务时触发 nag 提醒。

```
连续运行以下命令，不要更新任务列表：
1. 运行 echo "step 1"
2. 运行 echo "step 2"
3. 运行 echo "step 3"
4. 运行 echo "step 4"
```

**预期现象**：
- 第 4 次工具调用后，输出中出现 `[提醒] 你已经连续 N 次工具调用没有更新任务列表`
- 提醒内容包含当前任务列表的格式化输出
