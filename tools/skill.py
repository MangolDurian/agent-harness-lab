"""skill 工具 —— 用到什么知识，临时加载什么知识。

让 agent 能按需加载技能文件，获取完成特定任务所需的专业知识。
技能以 markdown 文件存放在项目根目录的 skills/ 下，每个文件代表一个技能。

核心思路：
  模型遇到不熟悉的领域 → 调用 load_skill("skill_name") →
  工具读取 skills/skill_name.md → 内容作为工具输出返回 →
  模型在后续对话中就能参考这些知识

这是一种"按需注入知识"的模式：
  - 不把所有知识塞进系统提示词（浪费上下文）
  - 而是模型自己判断需要什么，按需加载
"""
from __future__ import annotations

from pathlib import Path

# 技能文件目录（项目根目录下的 skills/）
_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _list_skills() -> str:
    """扫描 skills/ 目录，列出所有可用技能名称和简介。

    每个技能文件的第一行（通常是 markdown 标题）作为简介。
    """
    skills = sorted(_SKILLS_DIR.glob("*.md"))
    if not skills:
        return "（没有可用的技能文件）"

    lines = []
    for f in skills:
        name = f.stem
        # 读取第一行作为简介（通常是 "# 标题"）
        first_line = f.read_text(encoding="utf-8").split("\n", 1)[0]
        # 去掉 markdown 标题符号，得到纯文本
        desc = first_line.lstrip("#").strip()
        lines.append(f"- {name}: {desc}")

    return "可用技能：\n" + "\n".join(lines)


# ---- SCHEMA ----

SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill",
        # "Load a skill file to get expert knowledge for specific tasks."
        "description": (
            "加载技能文件，获取完成特定任务所需的专业知识和指引。"
            "技能内容会作为上下文的一部分返回。"
            "如果指定的技能不存在，会返回可用技能列表。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # "Name of the skill to load"
                    "description": "要加载的技能名称",
                },
            },
            "required": ["name"],
        },
    },
}


# ---- run ----


def run(name: str) -> str:
    """加载指定技能文件的内容并返回。

    如果技能不存在，返回可用技能列表。
    包含路径安全检查，防止读取 skills/ 目录外的文件。

    参数：
        name: 技能名称（对应 skills/ 目录下的 markdown 文件名）

    返回：
        技能文件的完整内容，或错误提示/可用列表
    """
    # 构造技能文件路径（自动补 .md 后缀）
    skill_file = (_SKILLS_DIR / name).with_suffix(".md").resolve()

    # 安全检查：确保解析后的路径仍在 skills/ 目录内
    # 防止通过 name="../core/llm" 等方式读取任意文件
    if not skill_file.is_relative_to(_SKILLS_DIR.resolve()):
        return f"错误：技能名称 '{name}' 不合法。"

    # 技能不存在时，返回可用列表（而不是报错）
    if not skill_file.exists():
        return f"未知技能 '{name}'。\n\n" + _list_skills()

    return skill_file.read_text(encoding="utf-8")
