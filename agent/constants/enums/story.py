"""
剧本模块相关的枚举常量。

消息角色 / 消息状态 / SSE 事件复用 agent.constants.enums.chat 中的
ChatRole / ChatMessageStatus / SseEvent（取值语义完全一致，不重复定义）；
本模块仅维护剧本域特有的取值（会话类型 / 消息产物类型 / 任务类型与状态 /
项目与关键帧状态）。
"""

from enum import Enum


class StorySessionType(str, Enum):
    """生成会话类型（story_sessions.type 取值）。"""

    GENERAL = "general"
    SCRIPT = "script"
    CHARACTER = "character"
    CHARACTER_ART = "character_art"
    KEYFRAME = "keyframe"


class StoryMessageKind(str, Enum):
    """会话消息产物类型（story_messages.kind 取值）。"""

    GENERAL = "general"
    SCRIPT = "script"
    CHARACTER = "character"
    ART = "art"
    KEYFRAME = "keyframe"


class StoryTaskType(str, Enum):
    """AI 生成任务类型（story_generation_tasks.task_type 取值）。"""

    SCRIPT = "script"
    CHARACTER = "character"
    CHARACTER_ART = "character_art"
    KEYFRAME = "keyframe"
    IMAGE = "image"


class StoryTaskStatus(str, Enum):
    """AI 生成任务状态流转（story_generation_tasks.status 取值）。

    pending -> queued -> generating -> succeeded / failed / cancelled。
    """

    PENDING = "pending"
    QUEUED = "queued"
    GENERATING = "generating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StoryProjectStatus(str, Enum):
    """项目生命周期（story_projects.status 取值）。

    删除采用软删除（DELETED，不参与列表与校验）；ARCHIVED 为归档态。
    """

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class StoryKeyframeStatus(str, Enum):
    """关键帧生命周期（story_keyframes.status 取值，业务层白名单校验）。

    draft（默认）→ generating（生成中）→ done（完成）/ failed（异常）；
    archived（归档后不参与导出）。
    """

    DRAFT = "draft"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"
    ARCHIVED = "archived"
