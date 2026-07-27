"""
密码哈希工具（bcrypt 直连封装）。

用户密码只存 bcrypt 哈希、永不明文落库（见 sys.sys_user.password 列注释）；
创建用户与重置密码时调用 hash_password，后续登录 change 校验时调用 verify_password。
不引入 passlib（已停止维护且与新版 bcrypt 存在兼容性问题）。
"""

import bcrypt

# bcrypt 明文输入上限为 72 字节，超出部分会被算法静默截断，这里显式拦截
_BCRYPT_MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    """
    将明文密码哈希为 bcrypt 字符串（含盐，可直接落库）。

    :param plain: 明文密码，非空且 UTF-8 编码后不超过 72 字节
    :return: bcrypt 哈希串（形如 '$2b$12$...'，长度 60，落 VARCHAR(100) 充裕）
    """
    if not plain:
        raise ValueError("密码不能为空")
    raw = plain.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("密码长度超过 72 字节上限")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    校验明文密码与已存哈希是否匹配（本阶段无登录消费，供后续 change 复用）。

    :param plain: 待校验的明文密码
    :param hashed: 数据库中存储的 bcrypt 哈希串
    :return: 匹配返回 True，不匹配或入参为空返回 False
    """
    if not plain or not hashed:
        return False
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
