"""
Agentic RAG 图相关的枚举常量（rag_graph 模块局部概念）。

集中管理 LangGraph 节点名、路由标签、文档相关性打分与消息角色，
避免在图定义与节点函数中散落魔法值字符串。
"""

from enum import Enum


class RagNode(str, Enum):
    """RAG 图节点名（同时用于节点注册与边的引用，必须保持一致）。"""

    GENERATE_QUERY_OR_RESPOND = "generate_query_or_respond"
    RETRIEVE = "retrieve"
    REWRITE_QUESTION = "rewrite_question"
    GENERATE_ANSWER = "generate_answer"


class RagRoute(str, Enum):
    """条件边路由标签。"""

    TOOLS = "tools"


class GradeScore(str, Enum):
    """文档相关性二值打分。"""

    YES = "yes"
    NO = "no"


class MessageRole(str, Enum):
    """对话消息角色。"""

    USER = "user"
