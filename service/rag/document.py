import asyncio
import uuid
from datetime import datetime
from typing import Any

from database.postgre_client import get_session
from database.rag.chunks import ChunkRepository
from database.rag.document import DocumentRepository
from database.rag.folder import FolderRepository
from database.rag.knowledge_base import KnowledgeBaseRepository
from exception.bad_except import bad_except
from utils.file_ingest import ingest_file
from utils.id import format_id
from utils.logger import logger
from utils.page import PageResult, build_page_result


class DocumentService:
    """
    文档业务层（编排 utils 解析 + PG 持久化 + Qdrant 向量化）。

    - upload：校验知识库 → 解析文件 → content_hash 判增量（跳过/新版本）→
      持久化文档与两级块树 → 同步知识库计数，全程单事务、不做向量化（D1/D5/D7）；
    - vectorize：请求域触发：校验 + 置 reindexing 后立即返回，真正的
      embed/写 Qdrant 由 vectorize_job 在后台任务中完成（成功 active / 失败 failed）；
    - update：仅改可编辑元数据，不触碰内容/哈希/版本/归属/状态（D6）；
    - list/get：浏览；statuses：批量状态查询，供前端轮询。
    """

    async def upload(
        self,
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
        tenant_id: str = "default",
    ) -> dict:
        """
        上传文件：解析 + 两级切块 + 持久化到 PG（不向量化）。

        content_hash 未变化的重复上传是幂等 no-op；变化则新增 document_version。
        知识库不存在、不支持的文件类型均转为友好失败。
        """
        # source_uri 缺省用文件名，作为 (kb, source_uri) 的增量比对键
        effective_source_uri = source_uri or filename

        async with get_session() as session:
            kb_repo = KnowledgeBaseRepository(session)
            doc_repo = DocumentRepository(session)
            chunk_repo = ChunkRepository(session)

            kb = await kb_repo.get(knowledge_base_id)
            if kb is None or kb.status == "deleted":
                bad_except(f"知识库不存在: {knowledge_base_id}")

            # 文件夹必须存在且与目标知识库一致，封死跨库悬挂引用
            if folder_id is not None:
                await self._require_folder_in_kb(
                    FolderRepository(session), folder_id, knowledge_base_id
                )

            # 解析 + 切块（纯预处理，不落库）；不支持类型在此抛业务异常
            parsed = ingest_file(filename, data)
            content = parsed["content"]
            content_hash = parsed["content_hash"]
            doc_type = parsed["doc_type"]
            parents = parsed["parents"]
            new_leaf_count = sum(len(p["children"]) for p in parents)

            existing = await doc_repo.find_by_source(
                knowledge_base_id, effective_source_uri
            )

            if existing is not None and existing.content_hash == content_hash:
                # 未变化：幂等 no-op，不新增块、不动计数
                logger.info(f"[RAG] 文档未变化，跳过重新切块: {effective_source_uri}")
                return existing.to_dict()

            if existing is not None:
                # 变化：新版本内容替换 + 新版本块集（旧版本块留待 vectorize 清理）
                old_leaf_count = await chunk_repo.count_level0(
                    existing.id, existing.version
                )
                doc = await doc_repo.replace_content(
                    existing, content, content_hash, doc_type
                )
                # 重新上传时按用户弹窗填写的文件夹/有效期/备注覆盖旧值
                self._apply_upload_meta(
                    doc, folder_id, valid_from, valid_until, metadata
                )
                await self._persist_chunk_tree(
                    chunk_repo, doc.id, doc.version, parents, doc.tenant_id
                )
                await kb_repo.adjust_counts(
                    kb, doc_delta=0, chunk_delta=new_leaf_count - old_leaf_count
                )
            else:
                # 新文档：version=1, status='pending'
                doc = await doc_repo.create(
                    knowledge_base_id=knowledge_base_id,
                    content=content,
                    content_hash=content_hash,
                    doc_type=doc_type,
                    source_uri=effective_source_uri,
                    source_system=source_system,
                    title=title or filename,
                    metadata=metadata,
                    folder_id=folder_id,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    tenant_id=tenant_id,
                )
                await self._persist_chunk_tree(
                    chunk_repo, doc.id, doc.version, parents, doc.tenant_id
                )
                await kb_repo.adjust_counts(kb, doc_delta=1, chunk_delta=new_leaf_count)

            await session.commit()
            return doc.to_dict()

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
        tenant_id: str = "default",
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
                tenant_id=tenant_id,
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
                        tenant_id=tenant_id,
                    )
                )
        await chunk_repo.bulk_insert(leaf_chunks)

    async def vectorize(self, doc_id: uuid.UUID) -> dict:
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

            # 并发拦截：已在同步中的文档拒绝重复触发（快速返回后的双提交窗口）
            if doc.status == "reindexing":
                bad_except("文档正在同步中，请稍后再试")

            kb = await kb_repo.get(doc.knowledge_base_id)
            if kb is None or kb.status == "deleted":
                bad_except(f"知识库不存在: {doc.knowledge_base_id}")

            leaf_chunks = await chunk_repo.fetch_level0(doc.id, doc.version)
            if not leaf_chunks:
                bad_except(f"文档没有可向量化的分块: {doc_id}")

            await doc_repo.set_status(doc, "reindexing")
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
                await asyncio.to_thread(
                    manager.upsert_hybrid, texts, payloads=payloads, ids=ids
                )

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

    async def statuses(self, ids: list[uuid.UUID]) -> list[dict]:
        """批量查询文档状态，返回 [{id, status}, ...]，未知 id 缺席（供前端轮询）。"""
        async with get_session() as session:
            repo = DocumentRepository(session)
            rows = await repo.fetch_status(ids)
            return [{"id": format_id(doc_id), "status": status} for doc_id, status in rows]

    async def reset_stale_reindexing(self) -> None:
        """启动清扫：把重启前残留的 reindexing 文档置为 failed（后台作业已丢失）。"""
        async with get_session() as session:
            repo = DocumentRepository(session)
            count = await repo.reset_stale_reindexing()
            await session.commit()
            if count:
                logger.warning(f"[RAG] 启动清扫：{count} 个残留 reindexing 文档已置为 failed")

    async def update(self, doc_id: uuid.UUID, changes: dict[str, Any]) -> dict:
        """
        仅元数据更新（title/folder_id/metadata/source_*/valid_*/last_verified_at/doc_type）；
        不触碰 content/content_hash/version/knowledge_base_id/status，不再切块/向量化。
        文档不存在时抛业务异常；文件夹必须与文档同属一个知识库。
        """
        async with get_session() as session:
            repo = DocumentRepository(session)
            if changes.get("folder_id") is not None:
                doc = await repo.get(doc_id)
                if doc is None or doc.status == "deleted":
                    bad_except(f"文档不存在: {doc_id}")
                await self._require_folder_in_kb(
                    FolderRepository(session),
                    changes["folder_id"],
                    doc.knowledge_base_id,
                )
            doc = await repo.update_metadata(doc_id, changes)
            if doc is None:
                bad_except(f"文档不存在: {doc_id}")
            await session.commit()
            return doc.to_dict()

    async def list(
        self,
        knowledge_base_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
    ) -> PageResult:
        """按知识库分页列出文档（排除软删除的），可选按 status 过滤。"""
        async with get_session() as session:
            repo = DocumentRepository(session)
            docs, total = await repo.list_by_kb(
                knowledge_base_id, page=page, size=size, status=status
            )
            return build_page_result([doc.to_dict() for doc in docs], total, page, size)

    async def get(self, doc_id: uuid.UUID) -> dict:
        """按 id 获取文档，不存在时抛业务异常。"""
        async with get_session() as session:
            repo = DocumentRepository(session)
            doc = await repo.get(doc_id)
            if doc is None or doc.status == "deleted":
                bad_except(f"文档不存在: {doc_id}")
            return doc.to_dict()
