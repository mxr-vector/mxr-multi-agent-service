from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from exception.bad_except import BadException
from utils.response import R
from utils.logger import logger


def _format_validation_error(err: dict) -> str:
    """对常见 Pydantic 校验错误进行友好中文转换"""
    err_type = err.get("type", "")
    loc_parts = err.get("loc", [])
    field_name = str(loc_parts[-1]) if loc_parts else "参数"
    ctx = err.get("ctx", {})

    field_labels = {
        "idea": "创作需求/提示词",
        "title": "标题",
        "content": "内容",
        "description": "描述",
        "style_key": "视频风格",
        "aspect_ratio": "画幅",
        "episodes": "集数",
        "tone": "基调",
        "prompt": "提示词",
        "name": "名称",
    }
    label = field_labels.get(field_name, field_name)

    if err_type == "string_too_long":
        max_len = ctx.get("max_length")
        return f"{label}超出最大长度限制（最多 {max_len} 字）"
    elif err_type == "string_too_short":
        min_len = ctx.get("min_length")
        return f"{label}长度不足（至少 {min_len} 字）"
    elif err_type == "missing":
        return f"缺少必填项 {label}"
    elif err_type == "greater_than_equal":
        ge = ctx.get("ge")
        return f"{label}必须大于等于 {ge}"
    elif err_type == "less_than_equal":
        le = ctx.get("le")
        return f"{label}必须小于等于 {le}"
    raw_msg = err.get("msg", "")
    return f"{label}: {raw_msg}" if label else raw_msg


def register_exception(app):
    """注册全局异常处理

    body.code 契约（客户端判定依据）：业务异常（BadException）返回 code=-1，
    HTTP 异常（HTTPException）返回 code=HTTP 状态码（404/401/422…）。
    """

    @app.exception_handler(BadException)
    async def bad_exception_handler(request: Request, exc: BadException):
        logger.warning(f"业务异常: {exc.msg}")
        return JSONResponse(content=R.fail(msg=exc.msg, code=exc.code).model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.warning(f"HTTP异常: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content=R.fail(msg=str(exc.detail), code=exc.status_code).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        logger.warning(f"参数验证失败: {exc.errors()}")
        # 只回 loc+msg：errors() 内含用户原始输入回显与内部字段结构，不外发
        detail = []
        friendly_reasons = []
        for err in exc.errors():
            loc_str = ".".join(str(p) for p in err.get("loc", []))
            detail.append({"loc": loc_str, "msg": err.get("msg")})
            friendly_reasons.append(_format_validation_error(err))

        err_summary = f": {'; '.join(friendly_reasons[:2])}" if friendly_reasons else ""
        return JSONResponse(
            status_code=422,
            content=R.fail(msg=f"参数验证失败{err_summary}", data=detail).model_dump(),
        )

    @app.exception_handler(AssertionError)
    async def assertion_exception_handler(request: Request, exc: AssertionError):
        # 断言消息可能携带内部细节（变量值/调用路径等），只入日志不回传客户端。
        # 须记录完整堆栈：库内部（SQLAlchemy/LangGraph 等）误用也会抛
        # AssertionError，仅记消息无法定位真实故障点
        logger.opt(exception=exc).warning("断言校验失败（响应统一通用文案）")
        return JSONResponse(content=R.fail(msg="参数校验失败").model_dump())

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("服务器内部错误", exc_info=exc)
        # 必须携带 500：缺省 200 会把真实故障在网关/监控/重试侧误判为成功
        return JSONResponse(
            status_code=500, content=R.fail(msg="服务器内部错误").model_dump()
        )

    logger.info("全局异常处理已注册")
