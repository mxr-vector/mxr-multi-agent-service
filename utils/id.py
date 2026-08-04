import uuid


def format_id(value: uuid.UUID | None) -> str | None:
    """将 UUID 序列化为无连字符的 32 位十六进制字符串。

    业务对外暴露的 id 统一去连字符（如 '018f...'），与 Qdrant collection 命名等
    场景保持一致；None 原样返回。FastAPI 的 uuid.UUID 路径/查询参数可直接解析
    该格式，因此前端回传时 round-trip 无损。
    """
    if value is None:
        return None
    return value.hex


def normalize_point_id(value) -> str:
    """把 Qdrant 返回的 point id 归一化为无连字符 hex，与业务侧 id 格式对齐。

    Qdrant 接受 32 位 hex 作为 point id（写入端统一用 format_id），但检索返回时
    会格式化为标准带连字符 UUID（或原样返回 int）。本函数兜底归一化，避免
    同一 chunk 的 point_id 与 payload.chunk_id 呈现两种格式造成比对/去重歧义。
    非 UUID 形态（如整数 id）原样字符串化。
    """
    try:
        return uuid.UUID(str(value)).hex
    except (ValueError, TypeError):
        return str(value)
