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
