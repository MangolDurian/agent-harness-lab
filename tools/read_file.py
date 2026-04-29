"""read_file 工具 —— 读取文件内容。

让 agent 能读取工作目录内的文件，并将内容返回给模型。
包含路径穿越防护，确保 agent 只能读取工作目录内的文件。
"""
from __future__ import annotations

import os
from pathlib import Path

# 最大输出长度，防止撑爆上下文窗口
_MAX_CHARS = 50_000

# 允许访问的根目录（当前工作目录）
_ROOT = Path(os.getcwd()).resolve()

SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the text content of a file within the working directory and return it.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read. Can be absolute or relative to the working directory.",
                },
            },
            "required": ["file_path"],
        },
    },
}


def _resolve_safe(file_path: str) -> Path:
    """将路径解析为绝对路径并校验它是否在工作目录内。

    参数：
        file_path: 用户/模型提供的文件路径

    返回：
        解析后的绝对路径

    异常：
        ValueError: 路径穿越了工作目录边界
    """
    # resolve() 会消除 .. 和符号链接，得到真实绝对路径
    target = (Path(file_path).expanduser()).resolve()

    # startswith 检查确保解析后的路径仍然在工作目录内
    if not str(target).startswith(str(_ROOT)):
        raise ValueError(
            f"Path traversal blocked: '{file_path}' resolves outside the working directory."
        )
    return target


def run(file_path: str) -> str:
    """读取指定路径的文件内容并返回。

    参数：
        file_path: 文件路径（绝对或相对路径）

    返回：
        文件的文本内容（截断到 50000 字符），或错误提示信息
    """
    # 安全校验：路径穿越检查
    try:
        target = _resolve_safe(file_path)
    except ValueError as e:
        return f"Error: {e}"

    # 文件不存在
    if not target.exists():
        return f"Error: file not found: {file_path}"

    # 不是普通文件（可能是目录）
    if not target.is_file():
        return f"Error: not a file: {file_path}"

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: cannot read as text (binary file?): {file_path}"
    except OSError as e:
        return f"Error: {e}"

    # 超长截断
    if len(content) > _MAX_CHARS:
        content = content[:_MAX_CHARS] + "\n...(truncated)"

    return content
