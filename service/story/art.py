"""
剧本模块立绘生成业务层：角色卡"生成立绘"异步任务（story-ai-workspace）。

- 点按触发：从角色卡消息（kind='character'）取当前卡片数据（含用户编辑修订）
  创建 character_art 生成任务后立即返回任务 id，前端轮询任务接口展示进度；
- 后台执行：model/image 工厂生成（同步 SDK 经 asyncio.to_thread）→ 落盘到
  会话资产目录（story/sessions/<session_id>/，沉淀时再复制进角色目录）→
  以 art 消息回填会话（携带来源卡片消息 id，供沉淀关联）；
- 失败路径同样落 art 消息（status=failed + error），抽屉内直接可见失败原因；
- 项目级互斥与剧本生成共用同一在途检查口径（story_generation_tasks）。
"""

import asyncio
import base64
import uuid
from datetime import datetime, timezone

import httpx
from uuid_utils.compat import uuid7

from agent.constants.enums.chat import ChatMessageStatus, ChatRole
from agent.constants.enums.story import StoryMessageKind, StoryTaskStatus, StoryTaskType
from agent.prompts.story import CARD_DATA_KEY
from core.config_snapshot import CFG
from database.postgre_client import get_session
from database.story.project import ProjectRepository
from database.story.session import (
    GenerationTaskRepository,
    MessageRepository,
    SessionRepository,
)
from exception.bad_except import bad_except
from model.image.factory import OUTPUT_FORMAT, generate_image
from service.story.session import (
    register_generation,
    release_session,
    reserve_session,
)
from service.story.storage import (
    SESSION_ASSET_ROOT,
    resolve_upload_path,
    rmdir_if_empty,
    unlink_quietly,
    write_seq_file,
)
from utils.logger import logger

# URL 形态生成结果下载超时（秒）
_URL_DOWNLOAD_TIMEOUT = 120.0


def _decode_image_content(content: str) -> bytes:
    """图像工厂返回内容解码：URL 直链下载或 base64 解码。"""
    if content.startswith(("http://", "https://")):
        resp = httpx.get(content, timeout=_URL_DOWNLOAD_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    return base64.b64decode(content)


class ArtGenerationService:
    """立绘生成业务层：任务创建、后台执行与 art 消息回填。"""

    async def start(
        self,
        ctx,
        message_id: uuid.UUID,
        size: str | None = None,
    ) -> dict:
        """从角色卡消息发起立绘生成，返回生成任务记录（前端轮询详情）。"""
        if not ctx.user_id:
            bad_except("立绘生成仅支持用户通道调用")
        async with get_session() as db:
            message, story_session, project = await self._assert_message_owned(
                db, message_id, ctx
            )
            session_id = message.session_id
            session_hex = session_id.hex
            # 会话级互斥（占位 sentinel）：与剧本生成共用注册表，防止同会话
            # 并发生成；后续失败归还占位；真实任务在 create_task 后注册
            reserve_session(session_hex)
            try:
                card = (message.params or {}).get(CARD_DATA_KEY)
                if not isinstance(card, dict):
                    bad_except("该消息不是可生成的角色卡")
                prompt = (card.get("art_prompt") or "").strip()
                if not prompt:
                    bad_except("该角色卡缺少出图提示词，请先编辑补全")
                if await GenerationTaskRepository(db).has_running(project.id):
                    bad_except("本项目已有生成任务进行中，请稍候")
                gen_task = await GenerationTaskRepository(db).create(
                    task_id=uuid7(),
                    project_id=project.id,
                    task_type=StoryTaskType.CHARACTER_ART.value,
                    session_id=session_id,
                    target_type=StoryMessageKind.CHARACTER.value,
                    target_id=message_id,
                    provider="image",
                    model=CFG.image.model_name,
                    prompt=prompt,
                    params={"card_message_id": message_id.hex, "card": card, "size": size},
                )
                await db.commit()
            except BaseException:
                release_session(session_hex)
                raise

        run_task = asyncio.create_task(
            self._run(
                gen_task_id=gen_task.id,
                project_id=project.id,
                session_id=session_id,
                card_message_id=message_id,
                card_name=str(card.get("name") or "角色"),
                prompt=prompt,
                size=size,
            )
        )
        register_generation(session_hex, run_task)
        return gen_task.to_dict()

    async def _assert_message_owned(self, db, message_id: uuid.UUID, ctx):
        """消息须存在且所属项目归属当前用户，返回 (消息, 会话, 项目)。"""
        message = await MessageRepository(db).get(message_id)
        if message is None:
            bad_except(f"消息不存在: {message_id.hex}")
        story_session = await SessionRepository(db).get(message.session_id)
        if story_session is None:
            bad_except(f"消息不存在: {message_id.hex}")
        project = await ProjectRepository(db).get(story_session.project_id)
        if (
            project is None
            or project.status == "deleted"
            or project.user_id != ctx.user_id
        ):
            bad_except(f"消息不存在: {message_id.hex}")
        return message, story_session, project

    async def _run(
        self,
        gen_task_id: uuid.UUID,
        project_id: uuid.UUID,
        session_id: uuid.UUID,
        card_message_id: uuid.UUID,
        card_name: str,
        prompt: str,
        size: str | None,
    ) -> None:
        """后台生成协程：生图 → 落盘 → art 消息回填 → 任务终态。"""

        async def _update_task(fields: dict) -> None:
            async with get_session() as db:
                row = await GenerationTaskRepository(db).get(gen_task_id)
                if row is not None:
                    await GenerationTaskRepository(db).update_fields(row, fields)
                    await db.commit()

        try:
            await _update_task(
                {
                    "status": StoryTaskStatus.GENERATING.value,
                    "progress": 10,
                    "started_at": datetime.now(timezone.utc),
                }
            )
            # 同步 SDK 经线程池执行（对齐项目"同步 IO 包 to_thread"约定）
            contents = await asyncio.to_thread(generate_image, prompt, size)
            if not contents or not contents[0]:
                raise RuntimeError("图像模型返回空结果")
            data = await asyncio.to_thread(_decode_image_content, contents[0])
            rel_dir = f"{SESSION_ASSET_ROOT}/{session_id.hex}"
            filename = await asyncio.to_thread(
                write_seq_file,
                resolve_upload_path(rel_dir),
                "art",
                OUTPUT_FORMAT,
                data,
            )
            image_file = f"{rel_dir}/{filename}"
            await _update_task({"progress": 90})

            async with get_session() as db:
                session_repo = SessionRepository(db)
                story_session = await session_repo.get(session_id)
                if story_session is None:
                    # 会话已被删除：丢弃产物，不留孤儿消息与文件（无外键需自守）
                    unlink_quietly(image_file)
                    rmdir_if_empty(rel_dir)
                    await _update_task(
                        {
                            "status": StoryTaskStatus.CANCELLED.value,
                            "finished_at": datetime.now(timezone.utc),
                            "error_message": "会话已删除，产物丢弃",
                        }
                    )
                    return
                message_repo = MessageRepository(db)
                seq = await message_repo.next_sequence(session_id)
                await message_repo.create(
                    message_id=uuid7(),
                    session_id=session_id,
                    role=ChatRole.ASSISTANT.value,
                    sequence=seq,
                    kind=StoryMessageKind.ART.value,
                    content=f"立绘：{card_name}",
                    image_file=image_file,
                    prompt=prompt,
                    params={
                        "card_message_id": card_message_id.hex,
                        "generation_task_id": gen_task_id.hex,
                        "source": "ai",
                    },
                )
                await session_repo.touch(
                    story_session, message_delta=1, message_at=datetime.now(timezone.utc)
                )
                # 项目生成冗余计数同步（与剧本生成同口径）
                project = await ProjectRepository(db).get(project_id)
                if project is not None:
                    await ProjectRepository(db).update_fields(
                        project,
                        {
                            "generation_count": await GenerationTaskRepository(
                                db
                            ).count_by_project(project_id),
                            "last_generated_at": datetime.now(timezone.utc),
                        },
                    )
                await db.commit()
            await _update_task(
                {
                    "status": StoryTaskStatus.SUCCEEDED.value,
                    "progress": 100,
                    "result_image_file": image_file,
                    "finished_at": datetime.now(timezone.utc),
                }
            )
        except asyncio.CancelledError:
            # 任务被取消（用户停止/会话删除）：任务行落取消终态，不留在途僵尸
            try:
                await _update_task(
                    {
                        "status": StoryTaskStatus.CANCELLED.value,
                        "finished_at": datetime.now(timezone.utc),
                        "error_message": "生成被取消",
                    }
                )
            except Exception as inner_exc:
                logger.error(f"[STORY] 立绘取消终态落库失败 task={gen_task_id.hex}: {inner_exc}")
            raise
        except Exception as exc:
            logger.exception(f"[STORY] 立绘生成失败 task={gen_task_id.hex}: {exc}")
            # 失败也落 art 消息（failed），抽屉内直接可见失败原因并可重试；
            # 会话已删除时跳过消息落库（不留孤儿），但任务仍落 failed 终态
            session_alive = True
            try:
                async with get_session() as db:
                    if await SessionRepository(db).get(session_id) is None:
                        logger.info(f"[STORY] 会话已删除，跳过失败消息落库 task={gen_task_id.hex}")
                        session_alive = False
                    else:
                        message_repo = MessageRepository(db)
                        seq = await message_repo.next_sequence(session_id)
                        await message_repo.create(
                            message_id=uuid7(),
                            session_id=session_id,
                            role=ChatRole.ASSISTANT.value,
                            sequence=seq,
                            kind=StoryMessageKind.ART.value,
                            content=f"立绘：{card_name}",
                            prompt=prompt,
                            status=ChatMessageStatus.FAILED.value,
                            error=str(exc)[:500],
                            params={
                                "card_message_id": card_message_id.hex,
                                "generation_task_id": gen_task_id.hex,
                                "source": "ai",
                            },
                        )
                        await db.commit()
            except Exception as inner_exc:
                logger.error(f"[STORY] 立绘失败消息落库失败: {inner_exc}")
            await _update_task(
                {
                    "status": StoryTaskStatus.FAILED.value,
                    "finished_at": datetime.now(timezone.utc),
                    "error_message": str(exc)[:500],
                }
            )
