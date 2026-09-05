"""
系统管理（sys schema）相关的枚举常量。

集中管理用户/角色/菜单/部门/字典等基础档案的状态取值，
避免在 routers/service/database 各层散落魔法值字符串。
"""

from enum import Enum


class RecordStatus(str, Enum):
    """基础档案启用态（sys_users/sys_roles/sys_menus/sys_depts/sys_dict_*.status 取值）。

    active 启用；disabled 停用（sys_users 当前仅数据标记，登录时拒绝）。
    """

    ACTIVE = "active"
    DISABLED = "disabled"
