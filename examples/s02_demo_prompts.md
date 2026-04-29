# s02 阶段成果验证清单

跑 `python agents/s02_multi_tool.py`，依次输入下面 4 个 prompt，对照预期现象。

---

## ✅ 1. read_file 单工具调用

**Prompt**

```
Read the file README.md and tell me what this project is about.
```

**预期**

- 出现 `[read_file] README.md` 黄字
- 没有 `$ ...` 黄字（模型选择 read_file 而非 bash cat）
- 绿字给出项目简介

**证明的机制** —— 模型理解了 read_file 的工具描述，知道读文件用 read_file 比 bash cat 更合适。

---

## ✅ 2. write_file → read_file 工具链

**Prompt**

```
Create a file called test_s02.txt with the content "Hello from s02!", then read it back to verify.
```

**预期**

- 出现 `[write_file] test_s02.txt (1 lines)` 黄字
- 出现 `[read_file] test_s02.txt` 黄字
- 绿字确认内容匹配

**证明的机制** —— 模型能编排多工具链：先写后读验证，工具间有逻辑依赖。

---

## ✅ 3. 模型自主选择工具

**Prompt**

```
Show me the contents of tools/bash.py
```

**预期**

- 模型可能选择 `read_file`（直接调工具）或 `bash`（用 cat 命令），两种都正确
- 无论选哪个，最终都返回 bash.py 的内容

**证明的机制** —— 模型根据工具描述自主决策，harness 不强制指定用哪个工具。

---

## ✅ 4. 路径穿越被拦截

**Prompt**

```
Read the file /etc/passwd
```

**预期**

- 出现 `[read_file] /etc/passwd` 黄字
- 输出包含 `Path traversal blocked` 错误信息
- 模型收到错误后会告诉用户路径被拦截

**证明的机制** —— `_resolve_safe()` 的安全检查生效，agent 无法读取工作目录之外的文件。

---

## 结业条件

4 个都 ✅ → s02 通过，可以进入 s03。

如果有任何一个失败：
- 1/2 失败多半是工具 schema 描述不够清晰，模型没选对工具
- 3 失败可能是路径安全检查逻辑有问题，回去检查 `_resolve_safe()`
- 4 失败要检查 handlers 注册是否正确
