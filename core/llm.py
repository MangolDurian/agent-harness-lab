"""Anthropic 客户端与模型配置的单点管理。

所有需要调用 LLM 的地方都从这里导入 client 和 MODEL，
避免在多处重复创建客户端实例或硬编码模型名。
"""
from __future__ import annotations  # 启用延迟类型注解求值，允许在类型提示中引用尚未定义的类型

import os  # 操作系统接口，用于读取环境变量

from anthropic import Anthropic  # Anthropic 官方 Python SDK
from dotenv import load_dotenv  # 从 .env 文件加载环境变量

# 加载项目根目录下的 .env 文件，override=True 表示覆盖已有的同名环境变量
load_dotenv(override=True)

# 如果用户配置了自定义的 base_url（比如智谱 AI 的代理地址），
# 就移除可能残留的 ANTHROPIC_AUTH_TOKEN，避免认证冲突
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 创建 Anthropic 客户端实例：
# - 如果设置了 ANTHROPIC_BASE_URL，就使用该地址（用于第三方兼容接口，如智谱 AI）
# - 如果没设置，就使用 Anthropic 官方默认地址
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL") or None)

# 从环境变量读取模型 ID，默认值为 claude-sonnet-4-5
# 使用 GLM 5.1 时，在 .env 中设置 MODEL_ID=glm-5.1
MODEL = os.environ.get("MODEL_ID", "claude-sonnet-4-5")
