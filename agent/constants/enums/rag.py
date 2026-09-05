"""
RAG 知识库域相关的枚举常量（检索工具 / 知识库与文档链路共用概念）。

集中管理二值判断分数、消息角色与知识库/文档的状态取值，
避免在工具实现与 routers/service/database 各层散落魔法值字符串。
"""

from enum import Enum


class GradeScore(str, Enum):
    """二值判断分数（用于反思逻辑判断上下文是否充分）。"""

    YES = "yes"
    NO = "no"


class MessageRole(str, Enum):
    """对话消息角色。"""

    USER = "user"


class KBVisibility(str, Enum):
    """知识库可见性（rag.knowledge_bases.visibility 取值）。

    public 任何人可见；department 部门边界内可见；private 仅 owner 与 admin。
    未知取值按最窄档（private）处理，判定逻辑见 service 层 assert_kb_visible。
    """

    PRIVATE = "private"
    DEPARTMENT = "department"
    PUBLIC = "public"


class KBStatus(str, Enum):
    """知识库生命周期（rag.knowledge_bases.status 取值）。

    删除采用软删除（DELETED）；仅 ACTIVE 参与缺省检索（ARCHIVED 已归档）。
    """

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class DocumentStatus(str, Enum):
    """文档生命周期（rag.documents.status 取值）。

    pending（新建未向量化）→ reindexing（重建索引中）→ active（可用）；
    failed（向量化异常，启动清扫兜底）；deleted（软删除，不参与检索）。
    """

    PENDING = "pending"
    REINDEXING = "reindexing"
    ACTIVE = "active"
    FAILED = "failed"
    DELETED = "deleted"
