"""
剧本模块剧本业务层：多版本保存与当前版本单点切换。

- 版本号项目内递增；保存时可选置为当前版本，首版自动成为当前版本；
- 切换当前版本先复位项目内全部 is_current 再置位（单点维护）；
- 手动编辑既有版本时来源标记为 'user'。
"""

import uuid

from sqlalchemy.exc import IntegrityError
from uuid_utils.compat import uuid7

from database.postgre_client import get_session
from database.story.project import ProjectRepository, ScriptRepository
from exception.bad_except import bad_except
from service.story.project import ProjectService

# 剧本来源白名单（业务层校验）
_SCRIPT_SOURCES = {"ai", "user", "upload"}


class ScriptService:
    """剧本业务层：版本追加与当前版本切换。"""

    def __init__(self) -> None:
        self._project_service = ProjectService()

    async def list(self, ctx, project_id: uuid.UUID, page: int, size: int):
        """项目剧本历史列表，版本号倒序。"""
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            items, total = await ScriptRepository(session).list_by_project(
                project_id, page, size
            )
            return [item.to_dict() for item in items], total

    async def save(self, ctx, project_id: uuid.UUID, payload) -> dict:
        """保存新剧本版本：版本号递增；首版或显式指定时置为当前版本。"""
        content = (payload.content or "").strip()
        if not content:
            bad_except("剧本内容不能为空")
        source = payload.source or "user"
        if source not in _SCRIPT_SOURCES:
            bad_except(f"剧本来源非法: {source}")
        async with get_session() as session:
            await self._project_service._assert_owned(session, project_id, ctx)
            # 行锁串行化同项目并发保存：先锁项目行再分配版本号，
            # 防两个请求读到同一 max(version) 后双插 UNIQUE(project_id, version)
            await ProjectRepository(session).get_for_update(project_id)
            repo = ScriptRepository(session)
            version = await repo.next_version(project_id)
            current = await repo.get_current(project_id)
            make_current = bool(payload.set_current) or current is None
            if make_current:
                await repo.clear_current(project_id)
            script = await repo.create(
                script_id=uuid7(),
                project_id=project_id,
                version=version,
                content=content,
                title=payload.title,
                source=source,
                is_current=make_current,
            )
            project_repo = ProjectRepository(session)
            project = await project_repo.get(project_id)
            await project_repo.recount_assets(project)
            try:
                await session.commit()
            except IntegrityError:
                # 行锁已串行化正常并发；此处为防御性兜底（如锁降级），映射为业务错误
                bad_except("剧本版本冲突，请重试")
            return script.to_dict()

    async def switch_current(self, ctx, script_id: uuid.UUID) -> dict:
        """切换当前版本：先复位项目全部剧本再置位所选版本。"""
        async with get_session() as session:
            repo = ScriptRepository(session)
            script = await repo.get(script_id)
            if script is None:
                bad_except("剧本不存在")
            await self._project_service._assert_owned(session, script.project_id, ctx)
            await repo.clear_current(script.project_id)
            script.is_current = True
            await session.flush()
            await session.commit()
            return script.to_dict()

    async def update(self, ctx, script_id: uuid.UUID, payload) -> dict:
        """编辑既有版本内容/标题（来源标记为 user）。"""
        async with get_session() as session:
            repo = ScriptRepository(session)
            script = await repo.get(script_id)
            if script is None:
                bad_except("剧本不存在")
            await self._project_service._assert_owned(session, script.project_id, ctx)
            fields = {}
            if payload.content is not None:
                content = payload.content.strip()
                if not content:
                    bad_except("剧本内容不能为空")
                fields["content"] = content
            if payload.title is not None:
                fields["title"] = payload.title
            if not fields:
                bad_except("没有可更新的字段")
            fields["source"] = "user"
            await repo.update_fields(script, fields)
            await session.commit()
            return script.to_dict()
