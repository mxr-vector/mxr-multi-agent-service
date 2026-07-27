import uuid

from database.postgre_client import get_session
from database.system.dept import DeptRepository
from exception.bad_except import bad_except


class DeptService:
    """
    部门业务层。

    负责编排持久层调用与业务规则：父节点存在性校验、防环校验
    （新父不能是自身或后代）、删除守卫（无子部门且无关联用户）。
    列表为扁平结构（树由前端组装），每个方法在共享会话中开启事务并提交。
    """

    async def create(
        self,
        name: str,
        parent_id: uuid.UUID | None = None,
        sort_order: int = 0,
        leader: str | None = None,
        status: str = "active",
    ) -> dict:
        """创建部门并返回其数据；提供 parent_id 时校验父部门存在。"""
        async with get_session() as session:
            repo = DeptRepository(session)
            if parent_id is not None:
                parent = await repo.get(parent_id)
                if parent is None:
                    bad_except(f"父部门不存在: {parent_id}")
            dept = await repo.create(
                name=name,
                parent_id=parent_id,
                sort_order=sort_order,
                leader=leader,
                status=status,
            )
            await session.commit()
            return dept.to_dict()

    async def list(
        self,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """扁平列表（sort_order 升序），供前端组树。"""
        async with get_session() as session:
            repo = DeptRepository(session)
            depts = await repo.list(keyword=keyword, status=status)
            return [d.to_dict() for d in depts]

    async def get(self, dept_id: uuid.UUID) -> dict:
        """按 id 获取部门，不存在时抛出业务异常。"""
        async with get_session() as session:
            repo = DeptRepository(session)
            dept = await repo.get(dept_id)
            if dept is None:
                bad_except(f"部门不存在: {dept_id}")
            return dept.to_dict()

    async def update(
        self,
        dept_id: uuid.UUID,
        name: str | None = None,
        sort_order: int | None = None,
        leader: str | None = None,
        status: str | None = None,
        parent_id: uuid.UUID | None = None,
        parent_id_set: bool = False,
    ) -> dict:
        """
        更新部门，不存在时抛出业务异常。

        变更 parent_id 时校验：父部门存在、不是自身、也不是自身的后代
        （防环，用内存 BFS 后代集合判断）。
        """
        async with get_session() as session:
            repo = DeptRepository(session)
            dept = await repo.get(dept_id)
            if dept is None:
                bad_except(f"部门不存在: {dept_id}")
            if parent_id_set and parent_id is not None:
                if parent_id == dept_id:
                    bad_except("父部门不能是自身")
                parent = await repo.get(parent_id)
                if parent is None:
                    bad_except(f"父部门不存在: {parent_id}")
                descendants = await repo.list_descendant_ids(dept_id)
                if parent_id in descendants:
                    bad_except("父部门不能是自身的下级部门")
            dept = await repo.update(
                dept_id,
                name=name,
                sort_order=sort_order,
                leader=leader,
                status=status,
                parent_id=parent_id,
                parent_id_set=parent_id_set,
            )
            await session.commit()
            return dept.to_dict()

    async def delete(self, dept_id: uuid.UUID) -> None:
        """带守卫的物理删除：存在子部门或关联用户时拒绝删除。"""
        async with get_session() as session:
            repo = DeptRepository(session)
            dept = await repo.get(dept_id)
            if dept is None:
                bad_except(f"部门不存在: {dept_id}")
            if await repo.has_children(dept_id):
                bad_except("部门下存在子部门，无法删除")
            if await repo.has_referencing_user(dept_id):
                bad_except("部门下存在用户，无法删除")
            await repo.delete(dept_id)
            await session.commit()
