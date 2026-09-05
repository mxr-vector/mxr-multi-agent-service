import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from utils.logger import logger


class AccessLogMiddleware(BaseHTTPMiddleware):
    """访问日志中间件"""

    async def dispatch(self, request: Request, call_next):
        # perf_counter 为单调时钟：不受系统时间跳变（NTP 校时等）影响，
        # 计时只用于耗时统计，必须用单调时钟而非 wall clock
        start_time = time.perf_counter()

        # 获取 IP
        client_host = request.client.host if request.client else "unknown"

        # 带 query string 的请求目标：排查检索/分页类带参请求时可定位到具体调用
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"

        # 执行请求
        try:
            response = await call_next(request)
        except Exception as exc:
            # 异常时也打日志（status=500）
            cost_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"[REQ] 500 {request.method} {target} from {client_host} "
                f"cost={cost_ms:.2f}ms"
            )
            raise exc

        # 正常响应时打日志
        cost_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            f"[REQ] {response.status_code} {request.method} {target} "
            f"from {client_host} cost={cost_ms:.2f}ms"
        )

        return response
