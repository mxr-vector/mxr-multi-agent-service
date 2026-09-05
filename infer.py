from contextlib import asynccontextmanager

import asyncio

from fastapi import FastAPI
from exception.gobal_exception import register_exception
from core.auto_import import load_routers
from middleware.auth import TokenAuthMiddleware
from middleware.request_id import RequestIDMiddleware
from middleware.access_log import AccessLogMiddleware
from agent.checkpoints.postgres import (
    cleanup_expired_checkpoints,
    close_checkpointer,
    open_checkpointer,
    start_ttl_task,
)
from agent.constants.enums.chat import sync_sse_event_dict
from agent.graph.chat_graph import chat_graph
from core.config_snapshot import CFG
from service.rag.chat import reset_stale_generating
from service.draw.diagram import reset_stale_generating as reset_stale_draw_generating
from service.story.session import reset_stale_generating_messages as reset_stale_story_generating
from service.rag.document import DocumentService
from utils.logger import logger
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from utils.env import ENV


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 配置快照加载（fail-fast）：模型配置与运行参数的运行期事实源，
    # 必须先于图节点/工厂的首次使用；缺配置或校验失败即抛异常拒绝启动
    await CFG.load()
    # 启动清扫 + 持久化装配：以下任务相互独立，并发执行缩短冷启动
    # （checkpointer open 最多等 30s，串行时冷启动时间为各项之和）。
    # 失败语义逐项保留：reset_stale_reindexing 失败仍 fail-fast 拒绝启动，
    # 会话域清扫/SSE 字典同步失败仅告警不阻断（与原实现一致）
    async def _guarded(name: str, coro) -> None:
        try:
            await coro
        except Exception as exc:
            logger.warning(f"{name} 启动清扫失败，已跳过: {exc}")

    startup = await asyncio.gather(
        DocumentService().reset_stale_reindexing(),
        open_checkpointer(),
        _guarded(
            "[CHAT]",
            reset_stale_generating(),
        ),
        _guarded(
            "[DRAW]",
            reset_stale_draw_generating(),
        ),
        _guarded(
            "[STORY]（确认已执行 story_alter_ai_workspace.sql 后重启恢复）",
            reset_stale_story_generating(),
        ),
        _guarded(
            "[SSE]",
            sync_sse_event_dict(),
        ),
        return_exceptions=True,
    )
    # fail-fast 语义保留：reindexing 清扫与 checkpointer 装配任一失败即拒绝启动
    for required in (startup[0], startup[1]):
        if isinstance(required, BaseException):
            raise required
    # checkpoint TTL：启动执行一次 + 每日循环后台任务（不动业务表）
    ttl_startup_failed = False
    try:
        await cleanup_expired_checkpoints()
    except Exception as exc:
        # 启动期失败（多为瞬时 DB 故障）：循环任务首轮改用 1 小时间隔重试，
        # 而非等满 24 小时导致过期 checkpoint 长期滞留
        ttl_startup_failed = True
        logger.warning(
            f"[CHAT] 启动期 checkpoint TTL 清理失败，交由循环任务重试: {exc}"
        )
    start_ttl_task(retry_first=ttl_startup_failed)
    yield
    # 关停：释放图单例与 checkpointer 资源（在途生成任务随事件循环关闭一并取消）
    chat_graph.reset()
    await close_checkpointer()


def create_app() -> FastAPI:
    """
    create_app 的 Docstring
    创建 FastAPI 对象
    :return: FastAPI 对象
    :rtype: FastAPI
    """
    # 配置允许跨域的域名（CORS_ORIGINS 逗号分隔，缺省 '*'；通配时禁用 Cookie 凭证）
    origins = ENV.cors_origins

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # 挂载静态文件（锚定项目根，与 upload_dir 同口径：换目录启动不失效）
    static_dir = ENV.base_path / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    # 挂载全局上传目录（头像等）：路径带 /public 前缀命中鉴权白名单，
    # <img> 等无法携带 token 的请求可直接访问
    ENV.upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        f"{ENV.base_url}/public/files",
        StaticFiles(directory=ENV.upload_dir),
        name="uploads",
    )
    # app.mount("/audio_db", StaticFiles(directory="audio_db"), name="audio_db")
    # 注册中间件（顺序见下方洋葱链说明）
    # Starlette 的 add_middleware 是 user_middleware.insert(0)：后 add 的在洋葱
    # 外层。add 顺序须与期望生效链相反，实际洋葱链（外→内）为：
    #   CORS → RequestID → AccessLog → TokenAuth
    # 即 AccessLog 在 TokenAuth 之外，认证失败的 401 短路同样留下访问日志
    # （认证攻击可观测）；RequestID 在最外层保证所有日志可按 request_id 关联。
    app.add_middleware(TokenAuthMiddleware)  # 认证（最内层）
    app.add_middleware(AccessLogMiddleware)  # 访问日志
    app.add_middleware(RequestIDMiddleware)  # 请求ID
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,  # 允许的域名列表
        allow_credentials="*" not in origins,  # 通配来源时不允许携带 Cookie
        allow_methods=["*"],  # 允许的请求方法，* 表示全部
        allow_headers=["*"],  # 允许的请求头
    )

    # 注册全局异常处理
    register_exception(app)

    # 路由注册
    load_routers(app)
    return app


app = create_app()


# 静态首页
@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(ENV.base_path / "static" / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(ENV.base_path / "static" / "favicon.ico")


# 启动（仅本地调试用）
if __name__ == "__main__":
    import uvicorn

    # reload 模式依赖多进程监控文件变更，生产误用会导致配置/内存状态漂移
    if ENV.is_prod:
        raise RuntimeError("生产环境禁止以热重载模式启动，请用 uvicorn 直接启动")
    uvicorn.run(
        "infer:app", host=ENV.server_host, port=ENV.server_port, reload=True, workers=1
    )
