"""write_file 工具 —— 写入文件内容。

让 agent 能将内容写入工作目录内的文件。
包含路径穿越防护，自动创建父目录。
"""
from __future__ import annotations

import os
from pathlib import Path

# 允许访问的根目录（当前工作目录）
_ROOT = Path(os.getcwd()).resolve()

SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        # "Write content to a file within the working directory. Creates parent directories if needed."
        "description": "将内容写入工作目录内的文件，如需要会自动创建父目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    # "Path to the file to write. Can be absolute or relative to the working directory."
                    "description": "要写入的文件路径，可以是绝对路径或相对于工作目录的路径。",
                },
                "content": {
                    "type": "string",
                    # "The text content to write to the file."
                    "description": "要写入文件的文本内容。",
                },
            },
            "required": ["file_path", "content"],
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
    target = (Path(file_path).expanduser()).resolve()

    if not target.is_relative_to(_ROOT):
        raise ValueError(
            # Path traversal blocked: '{file_path}' resolves outside the working directory.
            f"路径穿越已拦截：'{file_path}' 解析到了工作目录之外。"
        )
    return target


def run(file_path: str, content: str) -> str:
    """将内容写入指定路径的文件。

    参数：
        file_path: 文件路径（绝对或相对路径）
        content: 要写入的文本内容

    返回：
        成功/失败消息
    """
    # 安全校验：路径穿越检查
    try:
        target = _resolve_safe(file_path)
    except ValueError as e:
        # Error: {e}
        return f"错误：{e}"

    try:
        # 自动创建父目录（如果不存在）
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        # Error: failed to write file: {e}
        return f"错误：文件写入失败：{e}"

    # OK: wrote {len(content)} chars to {file_path}
    return f"成功：已将 {len(content)} 个字符写入 {file_path}"
