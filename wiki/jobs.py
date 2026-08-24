"""Async full-build and incremental dirty-partition job orchestration."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Sequence

from utils.logger import logger
from wiki.index import TopicIndexBuilder, TopicIndexBuildResult


@dataclass
class WikiJob:
    job_id: str
    scope_id: str
    kind: str
    status: str = "pending"
    total: int = 0
    completed: int = 0
    result: dict = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "scope_id": self.scope_id,
            "kind": self.kind,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _result_dict(result: TopicIndexBuildResult) -> dict:
    return {
        "scope_id": result.scope_id,
        "version": result.version,
        "pages": len(result.pages),
        "clusters": result.clusters.stats,
        "reviews": list(result.reviews),
    }


class WikiIndexJobRunner:
    """Process-local runner matching the document vectorize job lifecycle."""

    def __init__(self, builder: TopicIndexBuilder | None = None) -> None:
        self.builder = builder or TopicIndexBuilder()
        self.jobs: dict[str, WikiJob] = {}
        self.tasks: set[asyncio.Task] = set()

    def submit_full(
        self,
        scope_id: str,
        documents: Sequence[Any] | Callable[[], Any] | Callable[[], Awaitable[Any]],
        **kwargs,
    ) -> WikiJob:
        return self._submit("full", scope_id, documents, **kwargs)

    def submit_incremental(
        self,
        scope_id: str,
        documents: Sequence[Any] | Callable[[], Any] | Callable[[], Awaitable[Any]],
        **kwargs,
    ) -> WikiJob:
        return self._submit("incremental", scope_id, documents, **kwargs)

    def _submit(self, kind: str, scope_id: str, documents: Any, **kwargs) -> WikiJob:
        job = WikiJob(job_id=uuid.uuid4().hex, scope_id=str(scope_id), kind=kind)
        self.jobs[job.job_id] = job
        task = asyncio.create_task(self._run(job, documents, **kwargs))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    async def _resolve_documents(self, value: Any) -> Sequence[Any]:
        if callable(value):
            value = value()
        if inspect.isawaitable(value):
            value = await value
        return list(value or [])

    async def _run(self, job: WikiJob, documents: Any, **kwargs) -> None:
        job.status = "running"
        job.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            resolved = await self._resolve_documents(documents)
            job.total = len(resolved)
            if job.kind == "incremental":
                result = await self.builder.rebuild_dirty_partitions(
                    resolved, job.scope_id, **kwargs
                )
            else:
                result = await self.builder.build(resolved, job.scope_id, **kwargs)
            job.completed = job.total
            job.result = _result_dict(result) if result is not None else {"pages": 0}
            job.status = "succeeded"
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            logger.error(f"[WIKI] {job.kind} job failed ({job.job_id}): {exc}")
        finally:
            job.updated_at = datetime.now(timezone.utc).isoformat()

    def get(self, job_id: str) -> WikiJob | None:
        return self.jobs.get(job_id)


_runner = WikiIndexJobRunner()
_dirty_tasks: set[asyncio.Task] = set()


def submit_full_index(scope_id: str, documents: Any, **kwargs) -> WikiJob:
    return _runner.submit_full(scope_id, documents, **kwargs)


def submit_incremental_index(scope_id: str, documents: Any, **kwargs) -> WikiJob:
    return _runner.submit_incremental(scope_id, documents, **kwargs)


def get_job(job_id: str) -> dict | None:
    job = _runner.get(job_id)
    return job.to_dict() if job else None


async def mark_document_changed(document_id: str, scope_id: str) -> list[str]:
    """Mark pages dirty; Qdrant failure must not fail document ingestion."""
    try:
        from wiki.storage import TopicPageStore

        return await asyncio.to_thread(
            TopicPageStore(scope_id).mark_dirty,
            [str(document_id)],
        )
    except Exception as exc:
        logger.warning(f"[WIKI] dirty marking skipped for {document_id}: {exc}")
        return []


def enqueue_document_change(document_id: str, scope_id: str) -> None:
    """Fire-and-forget document -> dirty-page propagation."""
    try:
        task = asyncio.create_task(mark_document_changed(document_id, scope_id))
    except RuntimeError:
        return
    _dirty_tasks.add(task)
    task.add_done_callback(_dirty_tasks.discard)

