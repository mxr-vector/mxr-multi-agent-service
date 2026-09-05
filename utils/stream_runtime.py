"""流式生成运行时公共件：会话级在途任务注册表、旁路任务强引用、SSE 帧构造。

chat / draw / story 三条流式链路原先各自维护近乎相同的实现，此处收敛为
单一出口。注册表语义以 story 的占位式实现为准：acquire 原子占位（sentinel）
→ register 替换为真实任务 → done 条件注销，杜绝「互斥检查与注册之间隔着
await（kb 范围解析 / 属主校验 / 落库）」的并发穿透窗口。
"""

import asyncio
import json

from agent.constants.enums.chat import SseEvent, get_sse_event_names
from exception.bad_except import bad_except
from utils.logger import logger

# 占位哨兵：acquire 成功到 register 之间的互斥标记（独立对象，与 None 可区分）
_RESERVED = object()


class GenerationTaskRegistry:
    """会话级在途生成任务注册表：同会话互斥、停止取消、done 条件注销。

    条目取值为 _RESERVED（占位哨兵）或 asyncio.Task；done 回调仅在条目
    仍是本任务时才清除，防止误删占位后注册的新条目。占位必须用独立
    哨兵对象而非 None：dict.get 对「不存在」与「None 值」不可区分，
    用 None 占位会让占位期内的并发请求二次穿透互斥检查。
    """

    def __init__(self, occupied_msg: str) -> None:
        self._occupied_msg = occupied_msg
        self._tasks: "dict[str, asyncio.Task | object]" = {}

    def acquire(self, session_hex: str) -> None:
        """会话级生成互斥原子占位：已占用（哨兵或在途任务）则拒绝。"""
        existing = self._tasks.get(session_hex)
        if existing is None or (existing is not _RESERVED and existing.done()):
            self._tasks[session_hex] = _RESERVED
        else:
            bad_except(self._occupied_msg)

    def release(self, session_hex: str) -> None:
        """归还互斥占位（仅在条目仍为哨兵时清除，不影响真实任务）。"""
        if self._tasks.get(session_hex) is _RESERVED:
            self._tasks.pop(session_hex, None)

    def register(self, session_hex: str, task: asyncio.Task) -> None:
        """注册在途任务（替换占位哨兵），done 后条件清除。"""

        def _unregister(done_task: asyncio.Task) -> None:
            if self._tasks.get(session_hex) is done_task:
                self._tasks.pop(session_hex, None)

        self._tasks[session_hex] = task
        task.add_done_callback(_unregister)

    def cancel(self, session_hex: str) -> bool:
        """取消在途任务（幂等）：有在途任务返回 True，否则 False。"""
        task = self._tasks.get(session_hex)
        if task is None or task is _RESERVED or task.done():
            return False
        task.cancel()
        return True

    def in_flight(self, session_hex: str) -> bool:
        """是否有未结束的在途任务（含占位哨兵；供删除守卫等只读检查）。"""
        existing = self._tasks.get(session_hex)
        return existing is not None and (
            existing is _RESERVED or not existing.done()
        )


# 旁路后台任务的强引用集合（防 create_task 产物被 GC 提前回收）
_side_tasks: "set[asyncio.Task]" = set()


def _on_side_task_done(task: asyncio.Task) -> None:
    """旁路任务收尾：释放强引用并记录未处理异常（终态写失败不可静默）。"""
    _side_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"[RUNTIME] 旁路收尾任务失败: {exc!r}", exc_info=exc)


def spawn_side_task(coro, tag: str = "RUNTIME") -> asyncio.Task:
    """挂旁路后台任务并持强引用，done 时按 tag 记录未处理异常。"""
    task = asyncio.create_task(coro)
    _side_tasks.add(task)
    task.add_done_callback(_on_side_task_done)
    return task


def sse_frame(event_id: int, event: SseEvent, data) -> str:
    """构造标准 SSE 帧：id / event / data 三字段，data 为 JSON 序列化内容。

    事件名以系统字典 sse_event 为准（lifespan 启动同步缓存），
    缓存未就绪时回落枚举默认值。
    """
    payload = json.dumps(data, ensure_ascii=False)
    event_name = get_sse_event_names().get(event, event.value)
    return f"id: {event_id}\nevent: {event_name}\ndata: {payload}\n\n"
