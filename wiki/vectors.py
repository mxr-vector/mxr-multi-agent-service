"""Document-level vector construction for topic clustering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from wiki.models import WikiDocument


@dataclass(frozen=True)
class DocumentVector:
    document: WikiDocument
    text: str
    vector: tuple[float, ...]

    @property
    def document_id(self) -> str:
        return self.document.document_id


def _flatten_metadata(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        parts: list[str] = []
        for key in sorted(value):
            child = _flatten_metadata(
                value[key], f"{prefix}.{key}" if prefix else str(key)
            )
            parts.extend(child)
        return parts
    if isinstance(value, (list, tuple, set)):
        return [f"{prefix}: {item}" for item in value if str(item).strip()]
    if value is None:
        return []
    return [f"{prefix}: {value}" if prefix else str(value)]


def build_document_text(
    document: WikiDocument | Any, *, max_content_chars: int = 4000
) -> str:
    """Compose title + metadata + representative blocks in a stable order."""
    doc = (
        document
        if isinstance(document, WikiDocument)
        else WikiDocument.from_record(document)
    )
    blocks = list(doc.representative_blocks)
    if not blocks and doc.content:
        blocks = [doc.content[:max_content_chars]]
    else:
        blocks = [block[:max_content_chars] for block in blocks]
    pieces = [f"Title: {doc.title}" if doc.title else ""]
    metadata = _flatten_metadata(doc.metadata)
    if metadata:
        pieces.append("Metadata: " + " | ".join(metadata))
    if blocks:
        pieces.append("Representative blocks:\n" + "\n".join(blocks))
    return "\n".join(piece for piece in pieces if piece).strip()


def _batches(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_document_vectors(
    documents: Sequence[WikiDocument | Any],
    *,
    embedding_client: Any | None = None,
    batch_size: int = 64,
) -> list[DocumentVector]:
    """Embed document-level topic inputs in input order.

    Production callers leave ``embedding_client`` unset, which resolves the
    configured provider through ``EmbeddingFactory``.  The explicit seam is
    only for deterministic tests and offline pilot fixtures.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    normalized = [
        item if isinstance(item, WikiDocument) else WikiDocument.from_record(item)
        for item in documents
    ]
    if not normalized:
        return []
    client = embedding_client
    if client is None:
        from model.embeddings.factory import EmbeddingFactory

        client = EmbeddingFactory.get_client()
    texts = [build_document_text(document) for document in normalized]
    output: list[DocumentVector] = []
    for batch_documents, batch_texts in zip(
        _batches(normalized, batch_size), _batches(texts, batch_size)
    ):
        vectors = client.embed_documents(list(batch_texts))
        if len(vectors) != len(batch_texts):
            raise ValueError(
                f"embedding provider returned {len(vectors)} vectors for {len(batch_texts)} documents"
            )
        output.extend(
            DocumentVector(
                document=document,
                text=text,
                vector=tuple(float(value) for value in vector),
            )
            for document, text, vector in zip(batch_documents, batch_texts, vectors)
        )
    return output


document_vectors = build_document_vectors
