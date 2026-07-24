from datetime import datetime

# 统一的对外时间展示格式：年-月-日 时:分:秒
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_datetime(value: datetime | None) -> str | None:
    """将 datetime 美化为 '年-月-日 时:分:秒'（如 '2026-07-24 15:30:05'）。

    业务对外暴露的创建时间/修改时间统一使用该格式；None 原样返回。
    仅做展示格式化，不做时区转换（按存储时刻原样输出）。
    """
    if value is None:
        return None
    return value.strftime(DATETIME_FORMAT)
