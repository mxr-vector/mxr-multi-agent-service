"""CLI wrapper for offline wiki clustering parameter calibration."""

from __future__ import annotations

import argparse
import asyncio

from common import RESULTS_DIR, ensure_cfg_async, save_json
from dual_retrieval import get_eval_session
from wiki.calibration import calibrate_cluster_parameters
from wiki.models import WikiDocument
from wiki.vectors import build_document_vectors


async def load_documents(limit: int | None):
    from entity.rag.document import Document
    from sqlalchemy import select

    async with get_eval_session() as session:
        stmt = select(Document).where(Document.status == "active").order_by(Document.id)
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
    return [
        WikiDocument(
            document_id=doc.id.hex,
            title=doc.title or doc.id.hex,
            metadata=doc.doc_metadata or {},
            representative_blocks=((doc.content or "")[:4000],),
        )
        for doc in rows
    ]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate wiki clustering parameters")
    parser.add_argument("--max-documents", type=int, default=10000)
    parser.add_argument("--output", default=str(RESULTS_DIR / "wiki_parameter_calibration.json"))
    args = parser.parse_args()
    await ensure_cfg_async()
    documents = await load_documents(args.max_documents)
    vectors = build_document_vectors(documents, batch_size=64)
    result = calibrate_cluster_parameters(vectors)
    save_json(args.output, result)
    print(f"[wiki] calibration written: {args.output}; recommended={result['recommended']}")


if __name__ == "__main__":
    asyncio.run(main())

