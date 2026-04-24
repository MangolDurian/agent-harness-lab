"""bash 工具 —— agent 的第一双手。

让 agent 能在沙盒中执行 shell 命令，与真实世界交互。
包含危险命令黑名单过滤，防止 agent 执行破坏性操作。
"""
from __future__ import annotations  # 启用延迟类型注解求值

import os  # 操作系统接口，用于获取当前工作目录
import subprocess  # 子进程管理，用于执行 shell 命令

# 工具的 JSON Schema 定义，告诉 API 这个工具叫什么、接受什么参数
# 这个 schema 会作为 tools 列表的一项传给 Anthropic Messages API
SCHEMA = {
    "name": "bash",  # 工具名称，模型调工具时会用这个名字
    "description": "Run a shell command in the current working directory and return stdout+stderr.",  # 工具描述，帮助模型理解何时该用这个工具
    "input_schema": {  # 输入参数的 JSON Schema
        "type": "object",  # 参数是一个对象（字典）
        "properties": {  # 对象的属性定义
            "command": {  # 参数名
                "type": "string",  # 参数类型是字符串
                "description": "The shell command to execute.",  # 参数描述
            }
        },
        "required": ["command"],  # 必填参数列表
    },
}

# 危险命令黑名单：包含这些子串的命令会被拦截
# 这是最基本的安全防线，防止 agent 执行不可逆的破坏性操作
_DANGEROUS = ("rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "> /dev/sda")


def run(command: str) -> str:
    """执行一条 shell 命令并返回输出。

    参数：
        command: 要执行的 shell 命令字符串

    返回：
        命令的 stdout + stderr 合并输出（截断到 50000 字符），
        或错误提示信息
    """
    # 安全校验：如果命令中包含黑名单中的危险子串，直接拒绝执行
    if any(bad in command for bad in _DANGEROUS):
        return "Error: dangerous command blocked by harness."

    try:
        # 使用 subprocess.run 执行 shell 命令
        r = subprocess.run(
            command,  # 要执行的命令字符串
            shell=True,  # 通过 shell 解释执行（支持管道、重定向等语法）
            cwd=os.getcwd(),  # 在当前工作目录下执行
            capture_output=True,  # 捕获 stdout 和 stderr
            text=True,  # 以文本模式返回输出（而非字节）
            timeout=120,  # 超时时间 120 秒，防止命令卡死
        )

        # 合并 stdout 和 stderr，去掉首尾空白
        out = (r.stdout + r.stderr).strip()

        # 如果有输出就截断到 50000 字符（防止超长输出撑爆上下文窗口），
        # 没有输出则返回 "(no output)"
        return (out[:50_000] if out else "(no output)")

    except subprocess.TimeoutExpired:
        # 命令执行超时（超过 120 秒）
        return "Error: command timed out after 120s."

    except (FileNotFoundError, OSError) as e:
        # 命令不存在或操作系统错误（比如没有这个程序）
        return f"Error: {e}"
