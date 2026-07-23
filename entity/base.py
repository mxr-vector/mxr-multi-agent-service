from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    全局唯一的声明式基类（单一 metadata 注册表）。

    所有 ORM 模型与 DAO 统一从这里导入 Base，进程内只存在一份 metadata；
    放在 entity/ 而非 database/postgre_client.py，以避免模型与引擎模块之间的循环依赖。
    """

    pass
