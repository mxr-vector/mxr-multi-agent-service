from contextlib import asynccontextmanager

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
from agent.sub.chat_graph import reset_chat_graph
from service.rag.chat import reset_stale_generating
from service.rag.document import DocumentService
from utils.logger import logger
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from utils.env import ENV


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动清扫：重启丢失所有在途后台作业，残留 reindexing 文档统一置为 failed
    await DocumentService().reset_stale_reindexing()
    # 问答持久化装配：打开 psycopg 池 + AsyncPostgresSaver.setup（checkpoint 表自建）
    await open_checkpointer()
    # 问答启动清扫：残留 generating 消息统一置为 failed（崩溃恢复路径）
    await reset_stale_generating()
    # checkpoint TTL：启动执行一次 + 每日循环后台任务（不动业务表）
    try:
        await cleanup_expired_checkpoints()
    except Exception as exc:
        logger.warning(
            f"[CHAT] 启动期 checkpoint TTL 清理失败，交由循环任务重试: {exc}"
        )
    start_ttl_task()
    yield
    # 关停：释放图单例与 checkpointer 资源（在途生成任务随事件循环关闭一并取消）
    reset_chat_graph()
    await close_checkpointer()


def create_app() -> FastAPI:
    """
    create_app 的 Docstring
    创建 FastAPI 对象
    :return: FastAPI 对象
    :rtype: FastAPI
    """
    # 配置允许跨域的域名
    origins = ["*"]

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # 挂载静态文件
    app.mount("/static", StaticFiles(directory="static"), name="static")
    # 挂载全局上传目录（头像等）：路径带 /public 前缀命中鉴权白名单，
    # <img> 等无法携带 token 的请求可直接访问
    ENV.upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        f"{ENV.base_url}/public/files",
        StaticFiles(directory=ENV.upload_dir),
        name="uploads",
    )
    # app.mount("/audio_db", StaticFiles(directory="audio_db"), name="audio_db")
    # 注册中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,  # 允许的域名列表
        allow_credentials=True,  # 是否允许发送 Cookie
        allow_methods=["*"],  # 允许的请求方法，* 表示全部
        allow_headers=["*"],  # 允许的请求头
    )
    app.add_middleware(RequestIDMiddleware)  # 请求ID
    app.add_middleware(TokenAuthMiddleware)  # 认证
    app.add_middleware(AccessLogMiddleware)  # 访问日志

    # 注册全局异常处理
    register_exception(app)

    # 路由注册
    load_routers(app)
    return app


app = create_app()


# 静态首页
@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")


# 启动（仅本地调试用）
if __name__ == "__main__":
    import uvicorn

    # import os
    if ENV.is_prod:
        logger("生产环境，谨慎操作！")
    # uvicorn main:app --host 127.0.0.1 --port 8000 --reload
    uvicorn.run(
        "infer:app", host=ENV.server_host, port=ENV.server_port, reload=True, workers=1
    )
    logger.info("multi-agent-process Web服务器启动....")
