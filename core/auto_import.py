import importlib
import os
from fastapi import FastAPI, APIRouter
from utils.logger import logger
from utils.env import ENV


def _collect_routers(package: str, parent_router: APIRouter) -> None:
    """
    递归扫描 package（含无 __init__.py 的命名空间子包），
    把每个模块级 router 挂到 parent_router。

    pkgutil.iter_modules 不会枚举命名空间子包，因此这里直接遍历包的
    文件系统搜索路径：子目录按子包递归，.py 模块按需导入并注册其 router。
    """
    try:
        pkg = importlib.import_module(package)
    except ModuleNotFoundError:
        logger.error(f"未找到包: {package}")
        return

    # 命名空间包可能对应多个搜索路径
    for base_path in list(getattr(pkg, "__path__", [])):
        for entry in sorted(os.listdir(base_path)):
            if entry.startswith("_") or entry.startswith("."):
                continue
            full = os.path.join(base_path, entry)
            if os.path.isdir(full):
                # 子目录视为子包（命名空间包无需 __init__.py），递归扫描
                _collect_routers(f"{package}.{entry}", parent_router)
            elif entry.endswith(".py"):
                module = importlib.import_module(f"{package}.{entry[:-3]}")
                if hasattr(module, "router") and isinstance(module.router, APIRouter):
                    parent_router.include_router(module.router)


def load_routers(app: FastAPI, package: str = "routers"):
    """
    递归扫描 routers 包及所有子包（含命名空间子包），注册每个模块中的 router 对象。
    所有 router 统一挂在以 ENV.base_url 为前缀的父路由下。
    """
    parent_router = APIRouter(prefix=ENV.base_url)
    _collect_routers(package, parent_router)
    app.include_router(parent_router)
