"""
Agentic RAG 检索工具相关的枚举常量（agent.tools.rag_tools 使用的概念）。

集中管理二值判断分数与消息角色，避免在工具实现中散落魔法值字符串。
"""

from enum import Enum


class GradeScore(str, Enum):
    """二值判断分数（用于反思逻辑判断上下文是否充分）。"""

    YES = "yes"
    NO = "no"


class MessageRole(str, Enum):
    """对话消息角色。"""

    USER = "user"
