"""OpenAI 兼容客户端与模型配置的单点管理。

所有需要调用 LLM 的地方都从这里导入 client 和 MODEL，
避免在多处重复创建客户端实例或硬编码模型名。
本项目使用 OpenAI SDK 对接智谱 AI（GLM 5.1），
因为智谱 AI 的 API 采用 OpenAI 兼容格式，而非 Anthropic 格式。
"""
from __future__ import annotations  # 启用延迟类型注解求值，允许在类型提示中引用尚未定义的类型

import os  # 操作系统接口，用于读取环境变量

from dotenv import load_dotenv  # 从 .env 文件加载环境变量
from openai import OpenAI  # OpenAI 官方 Python SDK（兼容智谱等第三方服务）

# 加载项目根目录下的 .env 文件，override=True 表示覆盖已有的同名环境变量
load_dotenv(override=True)

# 从环境变量读取 API Key，用于认证
_api_key = os.environ.get("API_KEY", "")

# 从环境变量读取 API 基础地址，默认为智谱 AI 的 OpenAI 兼容接口
_base_url = os.environ.get("BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

# 创建 OpenAI 兼容客户端实例：
# - api_key: 你的 API 密钥
# - base_url: API 服务地址（智谱 AI 使用 OpenAI 兼容格式）
client = OpenAI(
    api_key=_api_key,  # API 密钥
    base_url=_base_url,  # API 基础地址
)

# 从环境变量读取模型 ID，默认值为 glm-5.1
MODEL = os.environ.get("MODEL_ID", "glm-5.1")
