# 类体内 `list` 方法会遮蔽内建 list，延迟注解求值以保住 list[...] 写法
from __future__ import annotations

import uuid

from database.postgre_client import get_session
from database.system.dict import DictDataRepository, DictTypeRepository
from exception.bad_except import bad_except
from utils.page import PageResult, build_page_result


class DictTypeService:
    """
    字典类型业务层。

    负责编排持久层调用与业务规则：type 键全局唯一、改 type 键时
    同事务级联更新字典数据、删除守卫（类型下无字典数据才可删）。
    每个方法在共享会话中开启事务并提交。
    """

    async def create(
        self,
        name: str,
        type: str,
        status: str = "active",
        remark: str | None = None,
    ) -> dict:
        """创建字典类型并返回其数据；type 键必须全局唯一。"""
        async with get_session() as session:
            repo = DictTypeRepository(session)
            if await repo.get_by_type(type) is not None:
                bad_except(f"字典类型键已存在: {type}")
            dict_type = await repo.create(
                name=name,
                type=type,
                status=status,
                remark=remark,
            )
            await session.commit()
            return dict_type.to_dict()

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        keyword: str | None = None,
        status: str | None = None,
    ) -> PageResult:
        """真分页返回字典类型列表（keyword 对 name/type 过滤、status 精确）。"""
        async with get_session() as session:
            repo = DictTypeRepository(session)
            items, total = await repo.list(
                page=page,
                size=size,
                keyword=keyword,
                status=status,
            )
            return build_page_result([i.to_dict() for i in items], total, page, size)

    async def get(self, dict_type_id: uuid.UUID) -> dict:
        """按 id 获取字典类型，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = DictTypeRepository(session)
            dict_type = await repo.get(dict_type_id)
            if dict_type is None:
                bad_except(f"字典类型不存在: {dict_type_id}")
            return dict_type.to_dict()

    async def update(
        self,
        dict_type_id: uuid.UUID,
        name: str | None = None,
        type: str | None = None,
        status: str | None = None,
        remark: str | None = None,
    ) -> dict:
        """
        更新字典类型，不存在时抛出业务异常。

        变更 type 键时校验新键全局唯一，并在同一事务内级联更新
        所有旧键的字典数据。
        """
        async with get_session() as session:
            repo = DictTypeRepository(session)
            dict_type = await repo.get(dict_type_id)
            if dict_type is None:
                bad_except(f"字典类型不存在: {dict_type_id}")
            old_type = dict_type.type
            if type is not None and type != old_type:
                existing = await repo.get_by_type(type)
                if existing is not None:
                    bad_except(f"字典类型键已存在: {type}")
                data_repo = DictDataRepository(session)
                await data_repo.cascade_update_type(old_type, type)
            dict_type = await repo.update(
                dict_type_id,
                name=name,
                type=type,
                status=status,
                remark=remark,
            )
            await session.commit()
            return dict_type.to_dict()

    async def delete(self, dict_type_id: uuid.UUID) -> None:
        """带守卫的物理删除：类型下仍有字典数据时拒绝删除。"""
        async with get_session() as session:
            repo = DictTypeRepository(session)
            dict_type = await repo.get(dict_type_id)
            if dict_type is None:
                bad_except(f"字典类型不存在: {dict_type_id}")
            data_repo = DictDataRepository(session)
            count = await data_repo.count_by_type(dict_type.type)
            if count > 0:
                bad_except("该类型下存在字典数据，无法删除")
            await repo.delete(dict_type_id)
            await session.commit()


class DictDataService:
    """
    字典数据业务层。

    负责编排持久层调用与业务规则：dict_type 必须指向已存在的字典类型、
    按类型键查询字典项（sort_order 升序，供前端下拉框）。
    """

    async def create(
        self,
        dict_type: str,
        label: str,
        value: str,
        sort_order: int = 0,
        is_default: bool = False,
        status: str = "active",
        remark: str | None = None,
    ) -> dict:
        """创建字典数据并返回其数据；dict_type 必须已存在。"""
        async with get_session() as session:
            type_repo = DictTypeRepository(session)
            if await type_repo.get_by_type(dict_type) is None:
                bad_except(f"字典类型不存在: {dict_type}")
            repo = DictDataRepository(session)
            dict_data = await repo.create(
                dict_type=dict_type,
                label=label,
                value=value,
                sort_order=sort_order,
                is_default=is_default,
                status=status,
                remark=remark,
            )
            await session.commit()
            return dict_data.to_dict()

    async def list(
        self,
        page: int = 1,
        size: int = 20,
        dict_type: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
    ) -> PageResult:
        """真分页返回字典数据列表（可按 dict_type/keyword/status 过滤）。"""
        async with get_session() as session:
            repo = DictDataRepository(session)
            items, total = await repo.list(
                page=page,
                size=size,
                dict_type=dict_type,
                keyword=keyword,
                status=status,
            )
            return build_page_result([i.to_dict() for i in items], total, page, size)

    async def list_by_type(self, dict_type: str) -> list[dict]:
        """按类型键取全量字典项（sort_order 升序），供前端下拉框消费。"""
        async with get_session() as session:
            repo = DictDataRepository(session)
            items = await repo.list_by_type(dict_type)
            return [i.to_dict() for i in items]

    async def get(self, dict_data_id: uuid.UUID) -> dict:
        """按 id 获取字典数据，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = DictDataRepository(session)
            dict_data = await repo.get(dict_data_id)
            if dict_data is None:
                bad_except(f"字典数据不存在: {dict_data_id}")
            return dict_data.to_dict()

    async def update(
        self,
        dict_data_id: uuid.UUID,
        label: str | None = None,
        value: str | None = None,
        sort_order: int | None = None,
        is_default: bool | None = None,
        status: str | None = None,
        remark: str | None = None,
    ) -> dict:
        """更新字典数据（dict_type 创建后不可变），不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = DictDataRepository(session)
            dict_data = await repo.get(dict_data_id)
            if dict_data is None:
                bad_except(f"字典数据不存在: {dict_data_id}")
            dict_data = await repo.update(
                dict_data_id,
                label=label,
                value=value,
                sort_order=sort_order,
                is_default=is_default,
                status=status,
                remark=remark,
            )
            await session.commit()
            return dict_data.to_dict()

    async def delete(self, dict_data_id: uuid.UUID) -> None:
        """物理删除字典数据，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = DictDataRepository(session)
            dict_data = await repo.get(dict_data_id)
            if dict_data is None:
                bad_except(f"字典数据不存在: {dict_data_id}")
            await repo.delete(dict_data_id)
            await session.commit()
