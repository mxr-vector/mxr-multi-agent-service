# rag-retrieval Specification

## Purpose

Connect the agentic RAG graph's retrieval layer to the knowledge-base document
pipeline. Retrieval is scoped to a knowledge base whose Qdrant collection is
derived internally from the knowledge base id; candidates carry provenance
fields so answers can attribute "which document / which chapter" without extra
lookups.

## Requirements

### Requirement: Knowledge-base-scoped hybrid retrieval
The RAG retrieval tool SHALL accept an optional knowledge base id. When a knowledge base id is provided, the tool SHALL derive the target Qdrant collection exclusively via the global collection naming function (`build_kb_collection_name`, producing `kb_{id.hex}_v1`) and run the hybrid search (dense + sparse with server-side RRF fusion) against that collection. When no knowledge base id is provided, the tool SHALL fall back to the demo collection `rag_documents` and log the fallback. The tool SHALL NOT query PostgreSQL and SHALL NOT accept an externally supplied collection name.

#### Scenario: Retrieval targets the knowledge base collection
- **WHEN** the retrieval tool is called with a knowledge base id whose documents have been vectorized
- **THEN** the hybrid search runs against that knowledge base's `kb_{id.hex}_v1` collection and returns candidates from the uploaded documents

#### Scenario: Missing knowledge base id falls back to the demo collection
- **WHEN** the retrieval tool is called without a knowledge base id
- **THEN** the hybrid search runs against the demo collection `rag_documents` and a fallback log entry is written

#### Scenario: Collection name cannot be injected
- **WHEN** a caller wants to target a specific knowledge base
- **THEN** the only way is passing the knowledge base id; the tool derives the collection name internally via the global naming function

### Requirement: Retrieval candidates carry provenance fields
Each retrieval candidate SHALL be a structured record containing `point_id`, `text`, `source`, `score`, `chapter_title`, `document_id`, and `chunk_id`. Provenance fields (`chapter_title`, `document_id`, `chunk_id`) SHALL be read leniently from the Qdrant payload: populated for knowledge base collections whose payloads carry them, and `None` for payloads without them (such as the demo collection). Candidate ordering SHALL follow the server-side fusion ranking with point-id deduplication preserved.

#### Scenario: Knowledge base candidates include chapter provenance
- **WHEN** retrieval hits a knowledge base collection whose points carry `chapter_title`/`document_id`/`chunk_id` payload fields
- **THEN** each returned candidate includes those values

#### Scenario: Demo collection candidates degrade gracefully
- **WHEN** retrieval hits the demo collection whose payloads lack provenance fields
- **THEN** candidates are returned with `chapter_title`, `document_id`, and `chunk_id` set to `None` and no error is raised

### Requirement: RAG graph state carries the knowledge base id across rounds
The RAG graph state SHALL include an optional `knowledge_base_id` field (hyphen-less hex string). The retrieve node SHALL pass it to the retrieval tool on every round, so all retrieval rounds of one invocation (including reflect-driven re-retrieval with rewritten queries) target the same knowledge base. When the field is absent the graph SHALL still run, with retrieval falling back to the demo collection.

#### Scenario: Multi-round retrieval stays within one knowledge base
- **WHEN** the graph is invoked with a `knowledge_base_id` and the reflect loop triggers additional retrieval rounds
- **THEN** every round's hybrid search targets the same knowledge base collection

#### Scenario: Graph without a knowledge base id keeps legacy behavior
- **WHEN** the graph is invoked without `knowledge_base_id` in the initial state
- **THEN** the invocation completes and retrieval uses the demo collection fallback

### Requirement: Answer sources expose provenance
The final graph output `sources` SHALL expose, for each reranked candidate, the fields `text`, `source`, `score`, `chapter_title`, `document_id`, and `chunk_id`, so consumers can render "which document / which chapter" attribution without additional lookups.

#### Scenario: Sources include chapter attribution
- **WHEN** the graph answers a question using candidates retrieved from a knowledge base collection
- **THEN** each entry in `sources` carries `chapter_title`, `document_id`, and `chunk_id` alongside `text`/`source`/`score`

### Requirement: Core retrieval chain decoupled from the demo ingestion script
The RAG retrieval chain (retrieval tool and graph modules) SHALL NOT import `utils.ducument`. The demo collection constant SHALL be owned by the retrieval tool module, and `utils/ducument.py` SHALL be self-contained and documented as a demo/manual-smoke script that is not part of the production ingestion path.

#### Scenario: No production import of the demo script
- **WHEN** the retrieval tool and RAG graph modules are inspected
- **THEN** neither imports `utils.ducument`

#### Scenario: Demo script remains runnable standalone
- **WHEN** `utils/ducument.py` is executed directly as a manual smoke script
- **THEN** it ingests demo web pages into the demo collection without importing agent-layer modules
