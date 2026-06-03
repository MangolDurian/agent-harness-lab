# s07 修复后实跑记录：Task System

本记录来自修复 `task` 真实 id 展示、过滤视图编号、事务回滚和 Web nag 文案之后的一次实际运行。

目标是保存修复后的真实输入、工具调用和 assistant 输出，便于和早期失败记录 `run-records/s07-task-system-run-raw.md` 对照。

## 1. Prompt 1：创建带子任务的分层计划

### 输入

```text
帮我规划一个"搭建 Web API"的项目，要求：
1. 先创建根任务"搭建 Web API"
2. 然后创建 3 个子任务，分别挂在根任务下面：
   - 设计数据库 schema
   - 实现 API 端点
   - 编写测试
3. 所有子任务初始状态为 pending
```

### 工具调用摘录

```text
task_create
1 tasks created
#1 [ ] 搭建 Web API
(1 待办)

task_create
3 tasks created
#1 [ ] 搭建 Web API
  #2 [ ] 设计数据库 schema
  #3 [ ] 实现 API 端点
  #4 [ ] 编写测试
(4 待办)
```

### assistant 输出

```text
项目已规划完成，当前任务结构如下：

| # | 任务 | 状态 | 父任务 |
|---|------|------|--------|
| 1 | 搭建 Web API | pending | — |
| 2 | 设计数据库 schema | pending | #1 |
| 3 | 实现 API 端点 | pending | #1 |
| 4 | 编写测试 | pending | #1 |

3 个子任务均已挂载在根任务"搭建 Web API"下，初始状态均为 `pending`。需要开始执行时随时告诉我！
```

## 2. Prompt 2：逐步更新状态

### 输入

```text
开始执行项目计划：
1. 把"设计数据库 schema"标记为 in_progress
2. 运行 ls data/ 看看当前目录结构
3. 完成后把"设计数据库 schema"标记为 completed
4. 把"实现 API 端点"标记为 in_progress
```

### 工具调用摘录

```text
task_update
#2→in_progress
#1 [ ] 搭建 Web API
  #2 [~] 设计数据库 schema
  #3 [ ] 实现 API 端点
  #4 [ ] 编写测试
(3 待办, 1 进行中)

bash
$ ls data/
tasks.json

task_update
#2→completed, #3→in_progress
#1 [ ] 搭建 Web API
  #2 [x] 设计数据库 schema
  #3 [~] 实现 API 端点
  #4 [ ] 编写测试
(2 待办, 1 进行中, 1 已完成)
```

### assistant 输出

```text
全部执行完毕，当前状态：

| # | 任务 | 状态 |
|---|------|------|
| 1 | 搭建 Web API | pending |
| 2 | 设计数据库 schema | ✅ completed |
| 3 | 实现 API 端点 | 🔄 in_progress |
| 4 | 编写测试 | pending |

**`ls data/` 结果**：目录下只有一个 `tasks.json` 文件。
```

## 3. Prompt 3：查看任务（状态筛选）

### 输入

```text
用 task_list 查看所有已完成的任务，然后再查看所有 pending 的任务。
```

### 工具调用摘录

```text
task_list
filter: completed
#2 [x] 设计数据库 schema
(2 待办, 1 进行中, 1 已完成)

task_list
filter: pending
#1 [ ] 搭建 Web API
  #4 [ ] 编写测试
(2 待办, 1 进行中, 1 已完成)
```

### assistant 输出

```text
查询结果如下：

### ✅ 已完成的任务
| # | 任务描述 |
|---|---------|
| 2 | 设计数据库 schema |

### ⏳ 待执行的任务
| # | 任务描述 |
|---|---------|
| 1 | 搭建 Web API |
| 4 | 编写测试 |

当前整体进度：2 个待办，1 个进行中，1 个已完成。
```

## 4. Prompt 4：退出重启后恢复

### 输入

```text
（执行 Prompt 1-3 后，输入 q 或 exit 退出 agent）

重新启动：
python agents/s07_task_system.py

输入：
调用 task_list 看看当前有哪些任务
```

### 工具调用摘录

```text
task_list
all tasks
#1 [ ] 搭建 Web API
  #2 [x] 设计数据库 schema
  #3 [~] 实现 API 端点
  #4 [ ] 编写测试
(2 待办, 1 进行中, 1 已完成)
```

### assistant 输出

```text
当前任务列表如下：

| # | 状态 | 任务描述 |
|---|------|---------|
| 1 | ⏳ 待办 | 搭建 Web API |
| 2 | ✅ 已完成 | 设计数据库 schema |
| 3 | 🔄 进行中 | 实现 API 端点 |
| 4 | ⏳ 待办 | 编写测试 |

整体进度：**2 个待办，1 个进行中，1 个已完成**。当前正在进行的任务是「实现 API 端点」。
```

## 5. Prompt 5：Nag 提醒

### 输入

```text
连续运行以下命令，不要更新任务列表：
1. 运行 echo "step 1"
2. 运行 echo "step 2"
3. 运行 echo "step 3"
4. 运行 echo "step 4"
```

### 工具调用摘录

```text
bash
$ echo "step 1"
step 1

bash
$ echo "step 2"
step 2

bash
$ echo "step 3"
step 3
[提醒] 你已经连续 3 次工具调用没有更新任务列表了。考虑调用 task_create 或 task_update 来追踪你的进度。
当前任务...

bash
$ echo "step 4"
step 4
[提醒] 你已经连续 4 次工具调用没有更新任务列表了。考虑调用 task_create 或 task_update 来追踪你的进度。
当前任务...
```

### assistant 输出

```text
四步全部完成：

1. `step 1` ✅
2. `step 2` ✅
3. `step 3` ✅
4. `step 4` ✅
```

## 修复验证结论

这次运行验证了 s07 的几个关键修复已经生效：

- **真实 id 可见**：任务列表直接展示 `#1`、`#2`、`#3`、`#4`，模型用 `#2` / `#3` 更新任务，不再把 `1.1` 这类显示序号误当 id。
- **父子层级仍然清晰**：根任务和子任务通过缩进表示，既保留层级关系，又不制造假 id。
- **过滤视图稳定**：`completed` 和 `pending` 视图都沿用真实 `#id`，不会重新编号导致模型看错。
- **持久化正常**：重启后 `task_list` 能恢复同一批任务和状态。
- **Web nag 已适配 task**：提醒文案从 `todo_write` 改为 `task_create` / `task_update`，并提示“任务列表”而不是“待办列表”。

和 `run-records/s07-task-system-run-raw.md` 对照看，这次实跑已经覆盖并修复了早期暴露的主要问题。
