# s07: Task System —— 大目标要拆成小任务，记在磁盘上

## 核心问题

s03 的 `tools/todo.py` 有三个痛点：
1. **纯内存**：进程退出任务就消失，无法跨会话恢复
2. **全量替换**：每次调用传入完整列表，不支持增量操作
3. **扁平结构**：没有父子层级，无法表达"大任务拆成子任务"

s07 新建 `tools/task.py`（与 `todo.py` 并存，不破坏 s03-s06），提供三个增量工具。

## 设计

### 三个增量工具

| 工具 | 操作 | 说明 |
|---|---|---|
| `task_create` | 创建 | 批量创建任务，支持 `parent_id` 指定父任务 |
| `task_update` | 更新 | 批量更新任务状态/描述，增量修改 |
| `task_list` | 查看 | 只读查看，可选按状态筛选 |

对比 todo_write 的全量替换：create 只加不改，update 只改指定的字段，list 只读不动。

### 单层父子层级

每个任务可选 `parent_id`，指向一个根任务。不支持孙子任务（`parent_id` 只能指向根任务）。

格式化输出（每行以真实 id `#N` 开头，父子关系用缩进表示）：
```
#1 [ ] Build API
  #2 [~] Design schema
  #3 [ ] Write endpoints
#4 [x] Setup project
```

行首的 `#N` 就是磁盘里的真实任务 id，也是 `task_update` 的 `id` 和 `task_create` 的 `parent_id` 要传的值。

> 早期版本曾用 `1.1` 这种"显示层级序号"，但它和真实 id 不一致，模型容易拿序号当 id 去 update 而报错（见 `run-records/s07-task-system-run-raw.md`）。现在统一改为直接展示真实 id，过滤视图也不再重新编号。

### 持久化

- 存储路径：`data/tasks.json`
- 格式：`{"next_id": 7, "tasks": {"1": {...}, "2": {...}}}`
- 原子写入：先写 `.tmp` 再 `rename`，防止写到一半崩溃丢失数据
- 每次写入即持久化：工具调用频率低，I/O 代价可忽略

### 数据模型

```python
# 单个任务
{
    "id": "1",              # 字符串，单调递增
    "text": "Build API",
    "status": "pending",    # pending / in_progress / completed
    "parent_id": null,      # null=根任务，"3"=3号任务的子任务
    "created_at": "ISO8601",
    "updated_at": "ISO8601",
}
```

### 验证规则

- create: `text` 必填，`parent_id` 必须指向已存在的根任务；create 与 update 都受"全局只能有一个 `in_progress`"约束
- update: `id` 必填且存在，全局只能有一个 `in_progress`
- 两个工具都支持批量操作，且都是**先全量校验、全部合法才提交**：任一项不合法时直接返回错误，不修改任何任务状态、不落盘（真正的整体回滚）

## Nag 适配

nag wrapper 从检测 `todo_write` 改为检测 `task_create`/`task_update`/`task_list`，
提醒文案从"更新待办列表"改为"更新任务列表"。

## 相比原版的三个差异

| 差异 | 原版 | 本项目 |
|---|---|---|
| 存储方式 | 内存中 TodoManager | JSON 文件持久化 + 原子写入 |
| 操作模式 | 全量替换（每次传完整列表） | 三个增量工具（create/update/list） |
| 任务层级 | 扁平列表 | 单层父子（parent_id），树形格式化输出 |
