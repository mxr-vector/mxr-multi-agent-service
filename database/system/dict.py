# 类体内 `list` 方法会遮蔽内建 list，延迟注解求值以保住 list[...] 写法
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.constants.enums.system import RecordStatus
from entity.system.dict import DictData, DictType
from utils.page import paginate
from utils.keyword import ilike_pattern


class DictTypeRepository:
    """
    字典类型持久层（DAO）。

    只负责纯粹的数据访问，不含业务规则（type 键唯一校验、删除守卫、
    级联更新的编排放 service 层）。共用 `database/postgre_client.py` 的会话，
    事务提交由 service 层控制。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        type: str,
        status: str = RecordStatus.ACTIVE,
        remark: str | None = None,
    ) -> DictType:
        """插入一条字典类型，id 由数据库 uuidv7() 生成。"""
        dict_type = DictType(
            name=name,
            type=type,
            status=status,
            remark=remark,
        )
        self.session.add(dict_type)
        await self.session.flush()
        return dict_type

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[DictType], int]:
        """
        真分页列表：服务端过滤（keyword 对 name/type 做 ILIKE、status 精确），
        total 为过滤后的总数。返回 (items, total)。
        """
        stmt = select(DictType)
        if keyword:
            pattern = ilike_pattern(keyword)
            stmt = stmt.where(
                DictType.name.ilike(pattern) | DictType.type.ilike(pattern)
            )
        if status:
            stmt = stmt.where(DictType.status == status)
        stmt = stmt.order_by(DictType.created_at.desc())
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def get(self, dict_type_id: uuid.UUID) -> DictType | None:
        """按 id 获取单条字典类型，不存在返回 None。"""
        return await self.session.get(DictType, dict_type_id)

    async def get_by_type(self, type: str) -> DictType | None:
        """按 type 键全局精确查询，不存在返回 None（供唯一性校验与存在性校验）。"""
        stmt = select(DictType).where(DictType.type == type)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        dict_type_id: uuid.UUID,
        name: str | None = None,
        type: str | None = None,
        status: str | None = None,
        remark: str | None = None,
    ) -> DictType | None:
        """更新字典类型字段，并显式刷新 updated_at；不存在返回 None。"""
        dict_type = await self.session.get(DictType, dict_type_id)
        if dict_type is None:
            return None
        if name is not None:
            dict_type.name = name
        if type is not None:
            dict_type.type = type
        if status is not None:
            dict_type.status = status
        if remark is not None:
            dict_type.remark = remark
        dict_type.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return dict_type

    async def delete(self, dict_type_id: uuid.UUID) -> None:
        """物理删除字典类型行（删除守卫在 service 层完成）。"""
        await self.session.execute(delete(DictType).where(DictType.id == dict_type_id))


class DictDataRepository:
    """
    字典数据持久层（DAO）。

    dict_type 以字符串逻辑关联 sys_dict_type.type，存在性校验放 service 层。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        dict_type: str,
        label: str,
        value: str,
        sort_order: int = 0,
        is_default: bool = False,
        status: str = RecordStatus.ACTIVE,
        remark: str | None = None,
    ) -> DictData:
        """插入一条字典数据，id 由数据库 uuidv7() 生成。"""
        dict_data = DictData(
            dict_type=dict_type,
            label=label,
            value=value,
            sort_order=sort_order,
            is_default=is_default,
            status=status,
            remark=remark,
        )
        self.session.add(dict_data)
        await self.session.flush()
        return dict_data

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        dict_type: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[DictData], int]:
        """
        真分页列表：可按 dict_type 精确过滤、keyword 对 label 做 ILIKE、
        status 精确过滤，按 sort_order 升序。返回 (items, total)。
        """
        stmt = select(DictData)
        if dict_type:
            stmt = stmt.where(DictData.dict_type == dict_type)
        if keyword:
            stmt = stmt.where(DictData.label.ilike(ilike_pattern(keyword)))
        if status:
            stmt = stmt.where(DictData.status == status)
        stmt = stmt.order_by(DictData.sort_order)
        items, total = await paginate(self.session, stmt, page, size)
        return list(items), total

    async def list_by_type(self, dict_type: str, status: str = "") -> list[DictData]:
        """按类型键取全量字典项（sort_order 升序），status 非空时按状态精确过滤。"""
        stmt = (
            select(DictData)
            .where(DictData.dict_type == dict_type)
            .order_by(DictData.sort_order)
        )
        if status:
            stmt = stmt.where(DictData.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, dict_data_id: uuid.UUID) -> DictData | None:
        """按 id 获取单条字典数据，不存在返回 None。"""
        return await self.session.get(DictData, dict_data_id)

    async def update(
        self,
        dict_data_id: uuid.UUID,
        label: str | None = None,
        value: str | None = None,
        sort_order: int | None = None,
        is_default: bool | None = None,
        status: str | None = None,
        remark: str | None = None,
    ) -> DictData | None:
        """更新字典数据字段，并显式刷新 updated_at；不存在返回 None。"""
        dict_data = await self.session.get(DictData, dict_data_id)
        if dict_data is None:
            return None
        if label is not None:
            dict_data.label = label
        if value is not None:
            dict_data.value = value
        if sort_order is not None:
            dict_data.sort_order = sort_order
        if is_default is not None:
            dict_data.is_default = is_default
        if status is not None:
            dict_data.status = status
        if remark is not None:
            dict_data.remark = remark
        dict_data.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return dict_data

    async def delete(self, dict_data_id: uuid.UUID) -> None:
        """物理删除字典数据行。"""
        await self.session.execute(delete(DictData).where(DictData.id == dict_data_id))

    async def count_by_type(self, dict_type: str) -> int:
        """统计某类型键下的字典数据量（供删除字典类型的守卫判断）。"""
        stmt = (
            select(func.count())
            .select_from(DictData)
            .where(DictData.dict_type == dict_type)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def cascade_update_type(self, old_type: str, new_type: str) -> None:
        """
        类型键变更时的级联更新：把所有 old_type 的字典数据
        改为 new_type（与字典类型更新同一事务，由 service 层编排提交）。
        """
        await self.session.execute(
            update(DictData)
            .where(DictData.dict_type == old_type)
            .values(dict_type=new_type, updated_at=datetime.now(timezone.utc))
        )
