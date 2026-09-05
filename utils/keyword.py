"""关键字模糊匹配辅助：转义 LIKE/ILIKE 通配符。"""


def ilike_pattern(keyword: str) -> str:
    """把用户关键字转为 ILIKE 字面匹配模式：转义 \\ % _ 后两端加 %。

    不转义时用户可借通配符放大扫描范围或探测命名（全量参数化 SQL 下
    不构成注入，仅行为问题）；PostgreSQL LIKE 的缺省转义字符为反斜杠，
    与本函数的转义写法匹配。
    """
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
