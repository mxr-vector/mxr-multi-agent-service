"""
Chat 问答父图相关的枚举常量（chat_graph / 问答服务共用概念）。

集中管理父图节点名、消息角色/状态与 SSE 事件名，
避免在图定义、服务层与路由层散落魔法值字符串。
"""

from enum import Enum

from utils.logger import logger


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


# ---------- sse_event 字典桥接 ----------
# 事件名的单一事实源为系统字典 sse_event（字典管理页维护，value 即协议事件名，
# label 为展示名），代码枚举仅作协议兜底。lifespan 启动时 sync_sse_event_dict()
# 读取字典构建发帧缓存，并幂等补录缺失的枚举项（新增事件只需改枚举）；
# 发帧经 get_sse_event_names() 取事件名，缓存未就绪时回落枚举默认值。
# 字典项的运行期改动（含禁用/自定义 value）需重启服务后生效。
SSE_EVENT_DICT_TYPE = "sse_event"

# 事件名缓存：SseEvent -> 帧 event 字段值；None 表示未同步（回落枚举默认值）
_event_names: dict[SseEvent, str] | None = None


async def sync_sse_event_dict() -> None:
    """lifespan 启动调用：读取 sse_event 字典构建事件名缓存，并补录缺失枚举项。

    字典类型不存在时一并补建；仅补录 value 完全缺失的枚举事件（幂等），
    已存在的项（含自定义 value / 禁用态）一律不动。读取或补录失败仅告警
    不阻断启动，发帧回落枚举默认值。
    """
    global _event_names
    try:
        from database.postgre_client import get_session
        from database.system.dict import DictDataRepository, DictTypeRepository

        async with get_session() as session:
            type_repo = DictTypeRepository(session)
            if await type_repo.get_by_type(SSE_EVENT_DICT_TYPE) is None:
                await type_repo.create(
                    name="SSE事件",
                    type=SSE_EVENT_DICT_TYPE,
                    remark="问答/绘图流式事件名，代码启动时自动同步",
                )
            data_repo = DictDataRepository(session)
            items = await data_repo.list_by_type(SSE_EVENT_DICT_TYPE)
            existing_values = {item.value for item in items}
            for event in SseEvent:
                if event.value not in existing_values:
                    await data_repo.create(
                        dict_type=SSE_EVENT_DICT_TYPE,
                        label=event.value,
                        value=event.value,
                        remark="代码自动同步",
                    )
            await session.commit()
            items = await data_repo.list_by_type(SSE_EVENT_DICT_TYPE)
        known = {item.value for item in items}
        _event_names = {
            event: event.value for event in SseEvent if event.value in known
        }
        logger.info(f"[SSE] 事件名字典已同步（{len(_event_names)}/{len(SseEvent)} 项）")
    except Exception as exc:
        _event_names = None
        logger.warning(f"[SSE] 事件名字典同步失败，回落枚举默认值: {exc}")


def get_sse_event_names() -> dict[SseEvent, str]:
    """返回 事件 -> 事件名 映射；缓存未就绪（非 lifespan 路径）时回落枚举默认值。"""
    return _event_names or {event: event.value for event in SseEvent}
