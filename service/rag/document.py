import asyncio
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError

from database.postgre_client import get_session
from database.rag.chunks import ChunkRepository
from database.rag.document import DocumentRepository
from database.rag.folder import FolderRepository
from database.rag.knowledge_base import KnowledgeBaseRepository
from exception.bad_except import bad_except
from service.rag.knowledge_base import assert_kb_visible, assert_kb_writable
from utils.file_ingest import ingest_file
from utils.id import format_id
from utils.logger import logger
from utils.page import PageResult, build_page_result
from utils.user_context import UserContext, resolve_dept_filter, resolve_owner_dept


class DocumentService:
    """
    文档业务层（编排 utils 解析 + PG 持久化 + Qdrant 向量化）。

    - upload：校验知识库 → 解析文件 → content_hash 判增量（跳过/新版本）→
      持久化文档与两级块树 → 同步知识库计数，全程单事务、不做向量化（D1/D5/D7）；
    - vectorize：请求域触发：校验 + 置 reindexing 后立即返回，真正的
      embed/写 Qdrant 由 vectorize_job 在后台任务中完成（成功 active / 失败 failed）；
    - update：仅改可编辑元数据，不触碰内容/哈希/版本/归属/状态（D6）；
    - delete：软删文档行 + 硬删全部 PG 块与 Qdrant 向量点 + 负向同步知识库计数；
    - list/get：浏览；statuses：批量状态查询，供前端轮询。
    """

    async def upload(
        self,
        ctx: UserContext,
        knowledge_base_id: uuid.UUID,
        filename: str,
        data: bytes,
        source_uri: str | None = None,
        source_system: str | None = None,
        title: str | None = None,
        metadata: dict | None = None,
        folder_id: uuid.UUID | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        dept_id: str | None = None,
        chunk_strategy: str = "char",
    ) -> dict:
        """
        上传文件：解析 + 两级切块 + 持久化到 PG（不向量化）。

        目标知识库须对当前上下文可见（数据权限收口）；归属部门经
        resolve_owner_dept 换算：仅 all 档尊重显式 dept_id（须存在），
        其余档位强制本人部门；换算结果为空时继承所在知识库的归属部门，
        仍为空（存量游离库）则拒绝上传，杜绝游离文档。
        chunk_strategy 为用户选择的切块策略（char/structure/semantic，默认
        char），生效策略（含 semantic 降级后的 char）记录于
        metadata.chunk_strategy；content_hash 与生效策略均未变化的重复上传是
        幂等 no-op，任一变化则新增 document_version。
        知识库不存在、不支持的文件类型/策略组合均转为友好失败。
        """
        # source_uri 缺省用文件名，作为 (kb, source_uri) 的增量比对键
        effective_source_uri = source_uri or filename
        owner_dept = await resolve_owner_dept(ctx, dept_id)

        async with get_session() as session:
            kb_repo = KnowledgeBaseRepository(session)
            doc_repo = DocumentRepository(session)
            chunk_repo = ChunkRepository(session)

            kb = await kb_repo.get(knowledge_base_id)
            await assert_kb_visible(kb, ctx, knowledge_base_id)
            # 写权限收口：与知识库元数据管理同口径，仅 owner/admin 可写（可见≠可写）
            await assert_kb_writable(kb, ctx)

            # 文档必须归属部门：未显式指定 / 用户无部门时继承所在知识库的归属部门
            # （新建知识库已强制归属），仅存量游离库继承后仍为空，拒绝上传
            if not owner_dept:
                owner_dept = kb.dept_id or ""
            if not owner_dept:
                bad_except("文档必须归属部门：所在知识库未归属部门，请先选择归属部门")

            # 文件夹必须存在且与目标知识库一致，封死跨库悬挂引用
            if folder_id is not None:
                await self._require_folder_in_kb(
                    FolderRepository(session), folder_id, knowledge_base_id
                )

            # 解析 + 切块（纯预处理，不落库）；不支持类型/策略组合在此抛业务异常。
            # 解析与语义切块是秒级 CPU/同步 IO 操作，丢线程池避免卡死事件循环
            parsed = await asyncio.to_thread(ingest_file, filename, data, chunk_strategy)
            content = parsed["content"]
            content_hash = parsed["content_hash"]
            doc_type = parsed["doc_type"]
            parents = parsed["parents"]
            effective_strategy = parsed["effective_strategy"]
            new_leaf_count = sum(len(p["children"]) for p in parents)
            # 生效策略随用户备注一起并入文档 metadata（新建与重传两条路径共用）
            merged_metadata = {**(metadata or {}), "chunk_strategy": effective_strategy}

            existing = await doc_repo.find_by_source(
                knowledge_base_id, effective_source_uri
            )

            # 幂等双条件：内容与生效策略都未变才跳过；换策略重传即触发重切
            if (
                existing is not None
                and existing.content_hash == content_hash
                and (existing.doc_metadata or {}).get("chunk_strategy", "char")
                == effective_strategy
            ):
                # 未变化：幂等 no-op，不新增块、不动计数
                logger.info(f"[RAG] 文档未变化，跳过重新切块: {effective_source_uri}")
                return existing.to_dict()

            if existing is not None and existing.status == "reindexing":
                # 后台向量化作业正在搬运该文档的分块，此时插入新版本块集
                # 会被作业的旧版本清理误删（数据丢失），拒绝重传直至同步完成
                bad_except("文档正在向量化中，请稍后再试")

            if existing is not None:
                doc = await self._replace_existing_doc(
                    doc_repo,
                    chunk_repo,
                    kb_repo,
                    kb,
                    existing,
                    content,
                    content_hash,
                    doc_type,
                    parents,
                    new_leaf_count,
                    folder_id=folder_id,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    merged_metadata=merged_metadata,
                )
            else:
                # 新文档：version=1, status='pending'。
                # create 后立即 flush 提前暴露 (kb, source_uri) 唯一冲突：
                # 并发上传同文件的 check-then-act 竞态由唯一索引兜底，
                # 冲突方回落到版本替换路径，不再产生重复文档
                try:
                    doc = await doc_repo.create(
                        knowledge_base_id=knowledge_base_id,
                        content=content,
                        content_hash=content_hash,
                        doc_type=doc_type,
                        source_uri=effective_source_uri,
                        source_system=source_system,
                        title=title or filename,
                        metadata=merged_metadata,
                        folder_id=folder_id,
                        valid_from=valid_from,
                        valid_until=valid_until,
                        dept_id=owner_dept,
                    )
                    await session.flush()
                    await kb_repo.adjust_counts(
                        kb, doc_delta=1, chunk_delta=new_leaf_count
                    )
                except IntegrityError:
                    await session.rollback()
                    existing = await doc_repo.find_by_source(
                        knowledge_base_id, effective_source_uri
                    )
                    if existing is None:
                        raise
                    if existing.status == "reindexing":
                        bad_except("文档正在向量化中，请稍后再试")
                    logger.warning(
                        f"[RAG] 并发上传同源文件命中唯一约束，回落版本替换: "
                        f"{effective_source_uri}"
                    )
                    # rollback 使事务内已取实例过期，kb 须重取后再计数
                    kb = await kb_repo.get(knowledge_base_id)
                    doc = await self._replace_existing_doc(
                        doc_repo,
                        chunk_repo,
                        kb_repo,
                        kb,
                        existing,
                        content,
                        content_hash,
                        doc_type,
                        parents,
                        new_leaf_count,
                        folder_id=folder_id,
                        valid_from=valid_from,
                        valid_until=valid_until,
                        merged_metadata=merged_metadata,
                    )

            await session.commit()
            self._enqueue_wiki_dirty(doc.id, doc.knowledge_base_id)
            return doc.to_dict()

    @staticmethod
    async def _replace_existing_doc(
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        kb_repo: KnowledgeBaseRepository,
        kb,
        existing,
        content: str,
        content_hash: str,
        doc_type: str | None,
        parents: list[dict[str, Any]],
        new_leaf_count: int,
        *,
        folder_id: uuid.UUID | None,
        valid_from: datetime | None,
        valid_until: datetime | None,
        merged_metadata: dict | None,
    ):
        """同源文档内容/策略变化：新版本内容替换 + 新版本块集（旧版本块留待 vectorize 清理）。

        上传主链路与并发唯一冲突回落链路共用。
        """
        old_leaf_count = await chunk_repo.count_level0(existing.id, existing.version)
        doc = await doc_repo.replace_content(existing, content, content_hash, doc_type)
        # 重新上传时按用户弹窗填写的文件夹/有效期/备注覆盖旧值
        DocumentService._apply_upload_meta(
            doc, folder_id, valid_from, valid_until, merged_metadata
        )
        await DocumentService._persist_chunk_tree(
            chunk_repo, doc.id, doc.version, parents, doc.dept_id
        )
        await kb_repo.adjust_counts(
            kb, doc_delta=0, chunk_delta=new_leaf_count - old_leaf_count
        )
        return doc

    @staticmethod
    def _enqueue_wiki_dirty(
        document_id: uuid.UUID, knowledge_base_id: uuid.UUID
    ) -> None:
        """Propagate document changes without coupling ingestion to wiki availability."""
        try:
            from wiki.jobs import enqueue_document_change

            enqueue_document_change(str(document_id), str(knowledge_base_id))
        except Exception as exc:
            logger.warning(f"[WIKI] failed to enqueue dirty propagation: {exc}")

    @staticmethod
    def _apply_upload_meta(
        doc,
        folder_id: uuid.UUID | None,
        valid_from: datetime | None,
        valid_until: datetime | None,
        metadata: dict | None,
    ) -> None:
        """重新上传（版本替换）时，把用户新填的文件夹/有效期/备注写回文档（仅非空字段生效）。"""
        if folder_id is not None:
            doc.folder_id = folder_id
        if valid_from is not None:
            doc.valid_from = valid_from
        if valid_until is not None:
            doc.valid_until = valid_until
        if metadata:
            doc.doc_metadata = {**(doc.doc_metadata or {}), **metadata}

    @staticmethod
    async def _require_folder_in_kb(
        folder_repo: FolderRepository,
        folder_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
    ) -> None:
        """校验文件夹存在且与文档同属一个知识库，否则抛业务异常。"""
        folder = await folder_repo.get(folder_id)
        if folder is None:
            bad_except(f"文件夹不存在: {folder_id}")
        if folder.knowledge_base_id != knowledge_base_id:
            bad_except("文件夹与目标知识库不一致")

    @staticmethod
    async def _persist_chunk_tree(
        chunk_repo: ChunkRepository,
        document_id: uuid.UUID,
        document_version: int,
        parents: list[dict[str, Any]],
        dept_id: str = "",
    ) -> None:
        """先插 level 1 父块拿到 id，再插 level 0 叶块并回填 parent_chunk_id。"""
        parent_chunks = [
            chunk_repo.build_chunk(
                document_id=document_id,
                document_version=document_version,
                level=1,
                chunk_index=p["chunk_index"],
                content=p["content"],
                char_start=p["char_start"],
                char_end=p["char_end"],
                chapter_title=p["chapter_title"],
                page_start=p["page_start"],
                page_end=p["page_end"],
                content_hash=p["content_hash"],
                dept_id=dept_id,
            )
            for p in parents
        ]
        await chunk_repo.bulk_insert(parent_chunks)

        leaf_chunks = []
        for parent_chunk, p in zip(parent_chunks, parents):
            for c in p["children"]:
                leaf_chunks.append(
                    chunk_repo.build_chunk(
                        document_id=document_id,
                        document_version=document_version,
                        level=0,
                        chunk_index=c["chunk_index"],
                        content=c["content"],
                        parent_chunk_id=parent_chunk.id,
                        char_start=c["char_start"],
                        char_end=c["char_end"],
                        chapter_title=c["chapter_title"],
                        page_start=c["page_start"],
                        page_end=c["page_end"],
                        content_hash=c["content_hash"],
                        dept_id=dept_id,
                    )
                )
        await chunk_repo.bulk_insert(leaf_chunks)

    async def vectorize(self, ctx: UserContext, doc_id: uuid.UUID) -> dict:
        """
        请求域触发向量化：校验文档/知识库/叶块后置 reindexing 并提交，立即返回；
        真正的 embed/写 Qdrant 由 vectorize_job 在后台任务中完成。
        文档/知识库不存在、无可向量化叶块、正在同步中均转为友好失败。
        """
        async with get_session() as session:
            kb_repo = KnowledgeBaseRepository(session)
            doc_repo = DocumentRepository(session)
            chunk_repo = ChunkRepository(session)

            doc = await doc_repo.get(doc_id)
            if doc is None or doc.status == "deleted":
                bad_except(f"文档不存在: {doc_id}")

            kb = await kb_repo.get(doc.knowledge_base_id)
            await assert_kb_visible(kb, ctx, doc.knowledge_base_id)
            await assert_kb_writable(kb, ctx)

            leaf_chunks = await chunk_repo.fetch_level0(doc.id, doc.version)
            if not leaf_chunks:
                bad_except(f"文档没有可向量化的分块: {doc_id}")

            # 并发拦截：条件 UPDATE 原子判定 + 置 reindexing，
            # 消除「读-判-写」窗口内的双触发竞态
            if not await doc_repo.set_status_if_not_reindexing(doc.id, "reindexing"):
                bad_except("文档正在同步中，请稍后再试")
            await session.commit()
            return doc.to_dict()

    async def vectorize_job(self, doc_id: uuid.UUID) -> None:
        """
        后台向量化作业（BackgroundTasks 调度）：自持 session 重读文档/知识库，
        把当前版本 level 0 叶块写入知识库的 qdrant_collection，point id 即 chunk id，
        灰度重建时于新点写入后清理旧版本（D4）；成功置 active，失败置 failed 并记日志。
        """
        from database.qdrant_client import QdrantManager

        try:
            async with get_session() as session:
                kb_repo = KnowledgeBaseRepository(session)
                doc_repo = DocumentRepository(session)
                chunk_repo = ChunkRepository(session)

                doc = await doc_repo.get(doc_id)
                if doc is None:
                    raise RuntimeError(f"文档不存在: {doc_id}")
                kb = await kb_repo.get(doc.knowledge_base_id)
                if kb is None:
                    raise RuntimeError(f"知识库不存在: {doc.knowledge_base_id}")

                leaf_chunks = await chunk_repo.fetch_level0(doc.id, doc.version)
                if not leaf_chunks:
                    raise RuntimeError(f"文档没有可向量化的分块: {doc_id}")

                valid_until = doc.valid_until.isoformat() if doc.valid_until else None
                texts = [c.content for c in leaf_chunks]
                ids = [format_id(c.id) for c in leaf_chunks]
                payloads = [
                    {
                        "document_id": format_id(doc.id),
                        "knowledge_base_id": format_id(doc.knowledge_base_id),
                        "document_version": doc.version,
                        "chunk_id": format_id(c.id),
                        "chapter_title": c.chapter_title,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "valid_until": valid_until,
                    }
                    for c in leaf_chunks
                ]

                manager = QdrantManager(kb.qdrant_collection)
                # upsert/delete 是同步阻塞调用（embedding HTTP + Qdrant IO），
                # 必须丢进线程池执行，否则会卡死事件循环：响应刷不出去（前端超时）、
                # /status 轮询也会挂起
                # 先写新点，再清理旧版本点（灰度重建，避免检索读到半空状态）
                vectorized_version = doc.version
                await asyncio.to_thread(
                    manager.upsert_hybrid, texts, payloads=payloads, ids=ids
                )

                # 清理旧版本前复核版本：upsert 期间若发生并发重传（版本已递增），
                # excluding_version 会把新版本的块当"旧版本"误删，造成数据丢失；
                # 此时跳过清理并保持状态，交由新版本自身的 vectorize 流程收尾
                doc = await doc_repo.get(doc_id)
                if doc is None or doc.version != vectorized_version:
                    logger.warning(
                        f"[RAG] 向量化期间文档版本已变化，跳过旧版本清理: {doc_id}"
                    )
                    return

                stale_leaves = await chunk_repo.fetch_level0_excluding_version(
                    doc.id, doc.version
                )
                if stale_leaves:
                    await asyncio.to_thread(
                        manager.delete_points,
                        [format_id(c.id) for c in stale_leaves],
                    )
                    await chunk_repo.delete_excluding_version(doc.id, doc.version)

                await doc_repo.set_status(doc, "active")
                await session.commit()
                logger.info(
                    f"[RAG] 已向量化 {len(ids)} 个叶块到集合: {kb.qdrant_collection}"
                )
        except Exception as exc:
            logger.error(f"[RAG] 文档向量化失败: {doc_id}: {exc}")
            # 失败落盘 failed；二次失败（如 DB 不可用）仅记日志，启动清扫兜底
            try:
                async with get_session() as session:
                    doc_repo = DocumentRepository(session)
                    doc = await doc_repo.get(doc_id)
                    if doc is not None:
                        await doc_repo.set_status(doc, "failed")
                        await session.commit()
            except Exception as inner:
                logger.error(f"[RAG] 回写 failed 状态失败: {doc_id}: {inner}")

    async def statuses(self, ctx: UserContext, ids: list[uuid.UUID]) -> list[dict]:
        """
        批量查询文档状态，返回 [{id, status}, ...]，供前端轮询。
        未知 id 与落在不可见知识库下的文档一律缺席（与不存在同语义，不泄露存在性）。
        """
        flt = await resolve_dept_filter(ctx)
        if flt.is_empty_boundary:
            return []
        async with get_session() as session:
            repo = DocumentRepository(session)
            rows = await repo.fetch_status(ids)
            if not rows:
                return []
            kb_repo = KnowledgeBaseRepository(session)
            kb_cache: dict[uuid.UUID, bool] = {}
            items = []
            for doc_id, kb_id, status in rows:
                if status == "deleted":
                    continue
                visible = kb_cache.get(kb_id)
                if visible is None:
                    kb = await kb_repo.get(kb_id)
                    visible = (
                        kb is not None
                        and kb.status != "deleted"
                        and await self._kb_visible(kb, flt, ctx)
                    )
                    kb_cache[kb_id] = visible
                if visible:
                    items.append({"id": format_id(doc_id), "status": status})
            return items

    @staticmethod
    async def _kb_visible(kb, flt, ctx: UserContext) -> bool:
        """statuses 批量链路的非抛出版可见性判定，语义与 assert_kb_visible 一致。"""
        if flt.owner is not None:
            return kb.owner == ctx.username
        if flt.dept_ids is None:
            return True
        return kb.dept_id in flt.dept_ids

    async def reset_stale_reindexing(self) -> None:
        """启动清扫：把重启前残留的 reindexing 文档置为 failed（后台作业已丢失）。"""
        async with get_session() as session:
            repo = DocumentRepository(session)
            count = await repo.reset_stale_reindexing()
            await session.commit()
            if count:
                logger.warning(
                    f"[RAG] 启动清扫：{count} 个残留 reindexing 文档已置为 failed"
                )

    async def delete(self, ctx: UserContext, doc_id: uuid.UUID) -> None:
        """
        删除文档：硬删 Qdrant 向量点（全部版本叶块，point id 即 chunk id）→
        硬删 PG 全部块 → 文档行置 status='deleted'（软删，与列表排除语义对齐）→
        负向同步知识库计数。先删向量点再提交 PG，避免提交后 Qdrant 失败
        遗留孤儿向量仍可被检索。同步中（reindexing）的文档拒绝删除，
        避免与后台向量化作业互相踩踏。
        """
        from database.qdrant_client import QdrantManager

        async with get_session() as session:
            kb_repo = KnowledgeBaseRepository(session)
            doc_repo = DocumentRepository(session)
            chunk_repo = ChunkRepository(session)

            doc = await doc_repo.get(doc_id)
            if doc is None or doc.status == "deleted":
                bad_except(f"文档不存在: {doc_id}")
            if doc.status == "reindexing":
                bad_except("文档正在同步中，请稍后再试")

            kb = await kb_repo.get(doc.knowledge_base_id)
            await assert_kb_visible(kb, ctx, doc.knowledge_base_id)
            await assert_kb_writable(kb, ctx)

            # 计数只回冲当前版本叶块数（与 upload 的增量口径对称），
            # 而 Qdrant 清理覆盖全部版本，兼顾未被 vectorize 清掉的旧版本点
            current_leaf_count = await chunk_repo.count_level0(doc.id, doc.version)
            all_leaves = await chunk_repo.fetch_level0_all(doc.id)
            if all_leaves:
                manager = QdrantManager(kb.qdrant_collection)
                # 同步阻塞调用，丢进线程池避免卡死事件循环（与 vectorize_job 同模式）
                await asyncio.to_thread(
                    manager.delete_points, [format_id(c.id) for c in all_leaves]
                )

            await chunk_repo.delete_by_document(doc.id)
            await doc_repo.set_status(doc, "deleted")
            await kb_repo.adjust_counts(
                kb, doc_delta=-1, chunk_delta=-current_leaf_count
            )
            await session.commit()
            self._enqueue_wiki_dirty(doc.id, doc.knowledge_base_id)
            logger.info(
                f"[RAG] 已删除文档 {doc_id}（清理 {len(all_leaves)} 个向量点，"
                f"集合: {kb.qdrant_collection}）"
            )

    async def update(self, ctx: UserContext, doc_id: uuid.UUID, changes: dict[str, Any]) -> dict:
        """
        仅元数据更新（title/folder_id/metadata/source_*/valid_*/last_verified_at/doc_type）；
        不触碰 content/content_hash/version/knowledge_base_id/status，不再切块/向量化。
        文档不存在时抛业务异常；文件夹必须与文档同属一个知识库。
        """
        async with get_session() as session:
            repo = DocumentRepository(session)
            doc = await repo.get(doc_id)
            if doc is None or doc.status == "deleted":
                bad_except(f"文档不存在: {doc_id}")
            kb = await KnowledgeBaseRepository(session).get(doc.knowledge_base_id)
            await assert_kb_visible(kb, ctx, doc.knowledge_base_id)
            await assert_kb_writable(kb, ctx)
            if changes.get("folder_id") is not None:
                await self._require_folder_in_kb(
                    FolderRepository(session),
                    changes["folder_id"],
                    doc.knowledge_base_id,
                )
            updated = await repo.update_metadata(doc_id, changes)
            if updated is None:
                bad_except(f"文档不存在: {doc_id}")
            await session.commit()
            self._enqueue_wiki_dirty(updated.id, updated.knowledge_base_id)
            return updated.to_dict()

    async def list(
        self,
        ctx: UserContext,
        knowledge_base_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        dept_ids: list[str] | None = None,
    ) -> PageResult:
        """
        按知识库分页列出文档（排除软删除的），可选按 status 过滤。
        先校验知识库对当前上下文可见（不可见与不存在同文案），
        再按 data_scope 强制部门边界：all 档尊重 dept_ids 参数，其余档忽略。
        """
        flt = await resolve_dept_filter(ctx, dept_ids)
        if flt.is_empty_boundary:
            return build_page_result([], 0, page, size)
        async with get_session() as session:
            kb = await KnowledgeBaseRepository(session).get(knowledge_base_id)
            await assert_kb_visible(kb, ctx, knowledge_base_id)
            repo = DocumentRepository(session)
            docs, total = await repo.list_by_kb(
                knowledge_base_id,
                page=page,
                size=size,
                status=status,
                dept_ids=flt.dept_ids,
            )
            # 列表不携带全文 content（单文档可达 MB 级，整页返回体积过大），
            # 全文经详情/分块接口按需获取
            return build_page_result(
                [doc.to_dict(include_content=False) for doc in docs],
                total,
                page,
                size,
            )

    async def get(self, ctx: UserContext, doc_id: uuid.UUID) -> dict:
        """按 id 获取文档（须落在可见知识库下），不存在时抛业务异常。"""
        async with get_session() as session:
            repo = DocumentRepository(session)
            doc = await repo.get(doc_id)
            if doc is None or doc.status == "deleted":
                bad_except(f"文档不存在: {doc_id}")
            kb = await KnowledgeBaseRepository(session).get(doc.knowledge_base_id)
            await assert_kb_visible(kb, ctx, doc.knowledge_base_id)
            return doc.to_dict()
