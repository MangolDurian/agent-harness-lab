"""bash 工具 —— agent 的第一双手。

让 agent 能在沙盒中执行 shell 命令，与真实世界交互。
包含危险命令黑名单过滤，防止 agent 执行破坏性操作。

本版本使用 OpenAI function calling 格式定义工具 Schema，
与 Anthropic 格式的区别：
  - 工具定义外包一层 {"type": "function", "function": {...}}
  - 参数定义用 "parameters" 而非 "input_schema"
"""
from __future__ import annotations

import os
import subprocess

COMMAND_TIMEOUT_SECONDS = 120
MAX_OUTPUT_LENGTH = 50_000

SCHEMA = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "在当前工作目录下执行一条 shell 命令，返回 stdout+stderr。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令。",
                }
            },
            "required": ["command"],
        },
    },
}

# 危险命令黑名单：包含这些子串的命令会被拦截
# 这是最基本的安全防线，防止 agent 执行不可逆的破坏性操作
_DANGEROUS = ("rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "> /dev/sda")


def _is_dangerous(command: str) -> bool:
    """检查命令是否包含危险子串。"""
    return any(bad in command for bad in _DANGEROUS)


def _truncate_output(text: str) -> str:
    """截断超长输出，防止撑爆上下文窗口。"""
    return text[:MAX_OUTPUT_LENGTH]


def run(command: str) -> str:
    """执行一条 shell 命令并返回输出。

    参数：
        command: 要执行的 shell 命令字符串

    返回：
        命令的 stdout + stderr 合并输出（截断到 MAX_OUTPUT_LENGTH 字符），
        或错误提示信息
    """
    if _is_dangerous(command):
        # Error: dangerous command blocked by harness.
        return "错误：危险命令已被安全策略拦截。"

    try:
        # shell=True 支持管道、重定向等语法
        r = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )

        out = (r.stdout + r.stderr).strip()
        return (_truncate_output(out) if out else "（无输出）")

    except subprocess.TimeoutExpired:
        # Error: command timed out after 120s.
        return f"错误：命令执行超时（{COMMAND_TIMEOUT_SECONDS} 秒）。"

    except (FileNotFoundError, OSError) as e:
        return f"错误：{e}"
