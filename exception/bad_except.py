"""
通用业务异常（预期内失败）。

业务侧只需调用 `bad_except("错误信息")` 即可抛出，由 `gobal_exception.py` 的
全局处理器统一捕获并转为 `R.fail` 输出，无需在 router 层逐个 try/except，
以此把「不存在 / 重复 / 删除守卫冲突」等预期失败与真正的 500 服务器错误区分开。
"""

from typing import NoReturn


class BadException(Exception):
    """业务预期内失败异常，携带错误信息与业务错误码。"""

    def __init__(self, msg: str, code: int = -1) -> None:
        self.msg = msg
        self.code = code
        super().__init__(msg)


def bad_except(msg: str, code: int = -1) -> NoReturn:
    """
    抛出业务异常，供业务侧直接调用：`bad_except("知识库不存在")`。

    :param msg: 面向调用方的错误信息，会原样出现在响应 msg 中
    :param code: 业务错误码，默认 -1（与 R.fail 一致）
    """
    raise BadException(msg, code)
