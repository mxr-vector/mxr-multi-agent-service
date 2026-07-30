"""
绘图模块相关的枚举常量。

消息角色 / 消息状态 / SSE 事件复用 agent.constants.enums.chat 中的
ChatRole / ChatMessageStatus / SseEvent（取值语义完全一致，不重复定义）；
本模块仅维护绘图特有的取值。
"""

from enum import Enum


class DrawSourceType(str, Enum):
    """图表版本来源（draw_diagram_versions.source_type 取值）。"""

    AI = "ai"  # 模型生成（mermaid_source 必有）
    USER = "user"  # drawio 编辑保存（drawio_xml / preview_file 必有）
