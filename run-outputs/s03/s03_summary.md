# agent-harness-lab 项目总结

1. **从零搭建 Agent Harness**：跟着 learn-claude-code 课程（s01~s12），逐步从零构建一个完整的 Agent 运行框架，每课完成课后作业验证掌握程度。

2. **循环不变、机制叠加**：核心设计原则是 `core/loop.py` 在 s01 写完后永远不改，后续每课只在外层（tools、skills、tasks 等）叠加新机制，体现渐进式架构。

3. **12 课递进学习路线**：从最简单的 Agent Loop + Bash 工具出发，逐步引入多工具、Todo 计划、子 Agent、技能加载、上下文压缩、任务系统、后台任务、团队协作、协议规范、自主认领、工作树隔离，最终构建出生产级 Agent 系统。
