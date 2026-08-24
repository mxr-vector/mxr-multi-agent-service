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
Each retrieval candidate SHALL be a structured record containing `point_id`, `text`, `source`, `score`, `chapter_title`, `document_id`, `chunk_id`, `page_start`, and `page_end`. Provenance fields (`chapter_title`, `document_id`, `chunk_id`, `page_start`, `page_end`) SHALL be read leniently from the Qdrant payload: populated for knowledge base collections whose payloads carry them, and `None` for payloads without them (such as the demo collection). Candidate ordering SHALL follow the server-side fusion ranking with point-id deduplication preserved.

#### Scenario: Knowledge base candidates include chapter provenance
- **WHEN** retrieval hits a knowledge base collection whose points carry `chapter_title`/`document_id`/`chunk_id` payload fields
- **THEN** each returned candidate includes those values

#### Scenario: Knowledge base candidates include page provenance
- **WHEN** retrieval hits a knowledge base collection whose points carry `page_start`/`page_end` payload fields
- **THEN** each returned candidate includes those page values

#### Scenario: Demo collection candidates degrade gracefully
- **WHEN** retrieval hits the demo collection whose payloads lack provenance fields
- **THEN** candidates are returned with `chapter_title`, `document_id`, `chunk_id`, `page_start`, and `page_end` set to `None` and no error is raised

### Requirement: RAG graph state carries the knowledge base id across rounds
The RAG graph state SHALL include an optional `knowledge_base_id` field (hyphen-less hex string). The retrieve node SHALL pass it to the retrieval tool on every round, so all retrieval rounds of one invocation (including reflect-driven re-retrieval with rewritten queries) target the same knowledge base. When the field is absent the graph SHALL still run, with retrieval falling back to the demo collection.

#### Scenario: Multi-round retrieval stays within one knowledge base
- **WHEN** the graph is invoked with a `knowledge_base_id` and the reflect loop triggers additional retrieval rounds
- **THEN** every round's hybrid search targets the same knowledge base collection

#### Scenario: Graph without a knowledge base id keeps legacy behavior
- **WHEN** the graph is invoked without `knowledge_base_id` in the initial state
- **THEN** the invocation completes and retrieval uses the demo collection fallback

### Requirement: Core retrieval chain decoupled from the demo ingestion script
The RAG retrieval chain (retrieval tool and graph modules) SHALL NOT import `utils.ducument`. The demo collection constant SHALL be owned by the retrieval tool module, and `utils/ducument.py` SHALL be self-contained and documented as a demo/manual-smoke script that is not part of the production ingestion path.

#### Scenario: No production import of the demo script
- **WHEN** the retrieval tool and RAG graph modules are inspected
- **THEN** neither imports `utils.ducument`

#### Scenario: Demo script remains runnable standalone
- **WHEN** `utils/ducument.py` is executed directly as a manual smoke script
- **THEN** it ingests demo web pages into the demo collection without importing agent-layer modules

### Requirement: RAG 图以重排序候选为终态输出
RAG 图 SHALL 终止于 rerank 节点，最终输出 SHALL 为 `reranked_docs`
（按相关性排序并裁剪到 top-k 的候选列表），MUST NOT 包含 `answer` 字段、
MUST NOT 调用对话生成模型。每个候选 SHALL 保留完整溯源字段
（`point_id`/`knowledge_base_id`/`text`/`source`/`score`/`chapter_title`/
`document_id`/`chunk_id`）。该图 SHALL 作为子图由 chat 父图在节点内
调用（显式状态映射），自身 MUST NOT 单独挂载 checkpointer。

#### Scenario: 子图输出重排序候选
- **WHEN** RAG 图以问题与 `knowledge_base_ids` 被调用并执行完成
- **THEN** 终态包含 `reranked_docs`（含全部溯源字段），不含 `answer`

#### Scenario: 子图不再调用对话模型
- **WHEN** 审查 RAG 图模块
- **THEN** 图内不存在 `generate_answer` 节点，不引用对话生成模型

### Requirement: RAG 子图终态输出检索指标
RAG 图终态 SHALL 额外输出 `metrics` 字段，包含 `reflect_rounds`
（实际执行的检索轮数）、`retrieved_count`（去重后累积候选总数）与
`reranked_count`（重排序裁剪后的候选数），供上层汇总推理复杂度。

#### Scenario: 终态携带检索指标
- **WHEN** RAG 图执行完成（含反思多轮与空候选短路两种路径）
- **THEN** 终态 `metrics` 含 reflect_rounds/retrieved_count/reranked_count
  且与实际执行轮数、候选数一致

### Requirement: 证据检索支持结构化多跳导航上下文

`knowledge_base_search` SHALL 接受由主题导航或前序证据生成的结构化导航上下文，并可在多跳场景下返回逐跳合并的证据候选。导航上下文 SHALL NOT 被序列化拼接到 dense、sparse 或 rerank 的原始证据 query 中；工具返回的证据候选 SHALL 继续携带原有溯源字段。

#### Scenario: 导航上下文不污染证据 query

- **WHEN** `knowledge_base_search` 收到主题页和前序跳锚点
- **THEN** dense、sparse 与 rerank 输入仍使用独立的原始/下一跳问句，候选不因通用主题摘要被稀释

#### Scenario: 多跳候选保持可引用

- **WHEN** 多跳检索完成并合并各跳候选
- **THEN** 每个证据候选仍包含 `document_id`、`chunk_id`、`source`、`score` 等原有溯源字段，主题页本身不进入答案来源

### Requirement: 多跳路径在线调用预算受控

默认多跳路径 SHALL 使用确定性锚点抽取和已有 embedding/检索/rerank 能力，不增加反思改写 LLM 调用。达到配置的跳数或查询预算后 SHALL 停止下钻；单跳和普通问题 SHALL 不增加检索阶段。

#### Scenario: 多跳预算耗尽

- **WHEN** 已执行跳数达到配置上限或累计候选达到预算
- **THEN** 系统停止生成新的跳查询，合并当前候选并返回预算指标

#### Scenario: 单跳问题不走多跳

- **WHEN** 问题只有一个可判定目标且没有导航锚点需求
- **THEN** 系统使用现有单轮证据检索路径，不产生额外的逐跳调用
