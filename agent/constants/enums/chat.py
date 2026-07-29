"""
Chat 问答父图相关的枚举常量（chat_graph / 问答服务共用概念）。

集中管理父图节点名、消息角色/状态与 SSE 事件名，
避免在图定义、服务层与路由层散落魔法值字符串。
"""

from enum import Enum


class ChatNode(str, Enum):
    """chat 父图节点名（同时用于节点注册与边的引用，必须保持一致）。"""

    CONDENSE = "condense"
    RAG_RETRIEVE = "rag_retrieve"
    RESPOND = "respond"


class ChatRole(str, Enum):
    """问答消息角色（chat_messages.role 取值）。"""

    USER = "user"
    ASSISTANT = "assistant"


class ChatMessageStatus(str, Enum):
    """问答消息状态生命周期（chat_messages.status 取值）。

    generating（占位）→ done / stopped（用户停止）/ failed（异常）。
    """

    GENERATING = "generating"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"


class SseEvent(str, Enum):
    """SSE 流式问答事件名（帧的 event 字段取值）。"""

    THINK = "think"
    ANSWER = "answer"
    SOURCES = "sources"
    DONE = "done"
    ERROR = "error"
