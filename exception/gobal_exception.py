from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from exception.bad_except import BadException
from utils.response import R
from utils.logger import logger


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
        detail = [
            {"loc": ".".join(str(p) for p in err.get("loc", [])), "msg": err.get("msg")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=R.fail(msg="参数验证失败", data=detail).model_dump(),
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
