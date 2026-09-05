import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Body, Path, Query
from pydantic import BaseModel

from agent.constants.enums.system import RecordStatus
from service.system.user import UserService
from utils.response import R
from utils.user_context import require_admin

# 创建路由
router = APIRouter(
    prefix="/system/users", tags=["OpenAPI - 系统用户管理"],
    dependencies=[Depends(require_admin)],
)

_service = UserService()


class UserCreate(BaseModel):
    """创建用户请求体（username 全局唯一，password 为明文、服务端哈希）。"""

    username: str
    password: str
    nickname: Optional[str] = None
    dept_id: Optional[uuid.UUID] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    status: str = RecordStatus.ACTIVE
    remark: Optional[str] = None


class UserUpdate(BaseModel):
    """更新用户请求体（不含 password，密码变更走重置密码；dept_id 可显式置空）。"""

    username: Optional[str] = None
    nickname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None
    dept_id: Optional[uuid.UUID] = None


class PasswordReset(BaseModel):
    """重置密码请求体（明文密码，服务端 bcrypt 哈希后覆盖）。"""

    password: str


class RoleAssign(BaseModel):
    """分配角色请求体（全量覆盖语义，传空列表即清空）。"""

    role_ids: list[uuid.UUID]


@router.post("")
async def create_user(payload: UserCreate = Body(...)):
    """创建用户（响应不含 password）。"""
    user = await _service.create(
        username=payload.username,
        password=payload.password,
        nickname=payload.nickname,
        dept_id=payload.dept_id,
        email=payload.email,
        phone=payload.phone,
        avatar=payload.avatar,
        status=payload.status,
        remark=payload.remark,
    )
    return R.success(data=user)


@router.get("")
async def list_users(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    size: int = Query(default=20, ge=1, le=200, description="每页数量"),
    keyword: Optional[str] = Query(default=None, description="按用户名/昵称模糊搜索"),
    dept_ids: Optional[list[uuid.UUID]] = Query(
        default=None,
        description="按部门过滤（可重复传参，多值 IN 匹配，用于部门子树过滤）",
    ),
    status: Optional[str] = Query(default=None, description="按状态精确过滤"),
):
    """真分页列出用户（响应不含 password，列表项聚合 dept_name 与 roles）。"""
    page_result = await _service.list(
        page=page, size=size, keyword=keyword, dept_ids=dept_ids, status=status
    )
    return R.success(data=page_result)


@router.get("/{user_id}")
async def get_user(user_id: uuid.UUID = Path(...)):
    """按 id 获取用户（响应不含 password）。"""
    user = await _service.get(user_id)
    return R.success(data=user)


@router.put("/{user_id}")
async def update_user(
    user_id: uuid.UUID = Path(...),
    payload: UserUpdate = Body(...),
):
    """更新用户基本信息（变更 username 时校验唯一，dept_id 可显式置空）。"""
    fields_set = payload.model_fields_set
    user = await _service.update(
        user_id,
        username=payload.username,
        nickname=payload.nickname,
        email=payload.email,
        phone=payload.phone,
        avatar=payload.avatar,
        status=payload.status,
        remark=payload.remark,
        dept_id=payload.dept_id,
        dept_id_set="dept_id" in fields_set,
    )
    return R.success(data=user)


@router.put("/{user_id}/password")
async def reset_password(
    user_id: uuid.UUID = Path(...),
    payload: PasswordReset = Body(...),
):
    """重置用户密码（服务端 bcrypt 哈希后覆盖存储）。"""
    await _service.reset_password(user_id, payload.password)
    return R.success(msg="密码重置成功")


@router.put("/{user_id}/roles")
async def assign_roles(
    user_id: uuid.UUID = Path(...),
    payload: RoleAssign = Body(...),
):
    """分配角色（全量覆盖：校验 role_ids 全部存在后先清空再插入）。"""
    await _service.assign_roles(user_id, payload.role_ids)
    return R.success(msg="分配成功")


@router.get("/{user_id}/roles")
async def list_user_roles(user_id: uuid.UUID = Path(...)):
    """查询用户已分配的角色 id 列表（供分配弹窗回显）。"""
    role_ids = await _service.list_role_ids(user_id)
    return R.success(data=role_ids)


@router.delete("/{user_id}")
async def delete_user(user_id: uuid.UUID = Path(...)):
    """物理删除用户（同事务清理其角色关联）。"""
    await _service.delete(user_id)
    return R.success(msg="删除成功")
