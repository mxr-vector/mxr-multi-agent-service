# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

## Overview

`multi-agent-service` is a FastAPI HTTP service for multi-agent orchestration and Agentic RAG (hybrid retrieval, reflection, rerank, multihop), plus an AI diagram-drawing workflow and RBAC management. It does **not** load models directly — inference is decoupled behind HTTP to a local vLLM server (or any OpenAI-compatible API) serving chat and pooling/embedding models. There is no offline mode. The companion frontend lives in `multi-agent-ui/` (Vue 3 + pnpm).

Code comments, docs, and commit messages are in Chinese (conventional-commit prefixes with Chinese subjects) — follow that convention. System design docs: `readme/RAG.md` (RAG), `readme/DRAW.md` (draw); DB schemas in `readme/sql/` (PostgreSQL ≥ 18, uses built-in `uuidv7()`).

## Commands

Package management uses **uv** (Python >= 3.13; README's `3.12` refers to the separate vLLM deployment). Default package index is the Tsinghua mirror (configured in `pyproject.toml`).

```bash
uv sync                            # install/lock dependencies
uv run python infer.py             # run the FastAPI service (uvicorn, reload, workers=1)
uv run python main.py              # rerank smoke demo
```

Frontend (`multi-agent-ui/`, pnpm):

```bash
pnpm dev                           # vite dev server
pnpm build                         # vue-tsc -b && vite build
```

There is **no test framework or linter configured**. Modules carry `if __name__ == "__main__"` blocks used as manual smoke tests — e.g. `uv run python agent/tools/rag_tools.py`. Any entry point that bypasses the FastAPI lifespan (demos, smoke blocks) must first load the config snapshot — `CFG.load_blocking()` in sync context, `await CFG.load()` inside an event loop — otherwise model factories raise "配置快照尚未加载".

## CodeGraph

This repo is indexed by CodeGraph (`.codegraph/` exists at the repo root). Before grep/find or reading files to locate or understand code, use the `codegraph_explore` MCP tool (or shell `codegraph explore "<symbols or question>"`) — one call returns verbatim line-numbered source plus call paths and blast radius, which you can Edit from directly.

## Environment configuration (required before running)

`utils/env.py` exposes a singleton `ENV` that reads `APP_ENV` (default `development`) and loads `env/.env.{APP_ENV}`, raising `FileNotFoundError` if missing. Only `env/.env.sample` is committed — copy it to `env/.env.development` first. External service hosts: append `env/host.txt` to `/etc/hosts`.

- Access config via `ENV.<property>` (e.g. `ENV.server_port`). Add settings as `@property` on `ENV_CONFIG` backed by `self.require(...)` so missing keys fail loudly. Never call `os.getenv` in feature code.
- **Config is two-track**: deployment-level settings (postgres/qdrant/connection, `EMBEDDING_*`) stay in env files — embedding model config is pinned because switching models invalidates the vector store. Runtime-tunable settings (chat/rewrite/visual/rerank model roles, RAG params like `RAG_FINAL_TOP_K`) live in DB (`sys_model_config` / `sys_config`) and are read through the config snapshot `CFG` (`core/config_snapshot.py`), refreshed on write with last-known-good fallback (frontend「模型管理 / 参数管理」pages, no restart).
- `ENV.is_prod` is true when `APP_ENV` is `prod` or `production`.

## Architecture

**Entry point** is `infer.py::create_app()`. The `lifespan` startup sequence is load-bearing: `CFG.load()` (fail-fast) → stale-job resets → open LangGraph Postgres checkpointer → SSE event dict sync → checkpoint TTL task. `main.py` is not the web service.

**Auto router registration** (`core/auto_import.py`): recursively scans the `routers` package for any module exposing a module-level `router: APIRouter` and mounts it under a parent prefixed with `ENV.base_url`. To add an endpoint group, create `routers/<name>.py` with `router = APIRouter(prefix=...)` — no manual registration. The codebase uses namespace packages with **no `__init__.py`** files.

**Middleware chain** (outer→inner): `CORSMiddleware` → `RequestIDMiddleware` (UUID into `request_id_ctx` ContextVar, returned as `X-Request-ID`) → `AccessLogMiddleware` (outside auth so 401s are logged) → `TokenAuthMiddleware` (requires `Authorization: Bearer <API_SECRET_KEY>` or a JWT, except `EXCLUDE_PATHS` and `/public*` / `/static*` path segments). Note `add_middleware` uses `insert(0)`: the last-added middleware is outermost, so the add order in `create_app` is reversed relative to this chain.

**Unified response + errors**: handlers return via `utils/response.py::R` (`R.success(data=...)` / `R.fail(msg=..., code=...)`), producing `{code, msg, data}`. `exception/gobal_exception.py::register_exception` converts `HTTPException`, `RequestValidationError`, `AssertionError`, and unhandled exceptions into that shape — raising these is the intended error path.

**Logging** (`utils/logger.py`): import the shared loguru `logger`; it injects `request_id` into every record and writes rotated dated files under `logs/`. Prefer it over `print`.

**Layering** (strict): `routers/` (HTTP) → `service/` (business logic) → `database/` (CRUD per schema: `rag/`, `draw/`, `system/`) plus `agent/` (LangGraph orchestration: `graph/` parent graph, `tools/`, `prompts/`, `checkpoints/`) and `model/` (provider clients behind factories).

### Model access — factories only

`model/{chat,embeddings,rerank,compression,visual,sparse,image}` each expose a factory; business code never imports concrete clients or passes provider/model names. Chat: `build_chat_model()` rebuilds per call from `CFG.chat` so hot-updated config takes effect next request. Embeddings: `EmbeddingFactory.get_client()` resolves `EMBEDDING_PROVIDER` (spec: `openspec/specs/embedding/spec.md`); every client subclasses `BaseEmbeddingClient` returning pure vectors (`embed_documents` preserves input order, `embed_query` returns one vector); provider quirks stay encapsulated in adapters; optional capabilities raise `NotImplementedError` on the base class. Cohere is registered but deprecated (incompatible SDK) — keep it registered. `model/embeddings/langchain_adapter.py` is the bridge when LangChain integration is needed; prefer official SDK clients over LangChain wrappers.

### RAG pipeline (Agentic)

Question flow: `agent/graph/chat_graph.py` (LangGraph parent graph, module-level singleton `chat_graph`, lazy-compiled; checkpointer `agent/checkpoints/postgres.py` persists multi-turn state keyed by `thread_id = session_id`; TTL cleanup task; history falls back to `rag.chat_messages` business table) → the chat model autonomously calls the `knowledge_base_search` tool (`agent/tools/rag_tools.py`) in a tool-calling loop → inside the tool: hybrid recall (dense + jieba BM25 sparse, server-side RRF fusion via `agent/tools/document.py::hybrid_retrieve_multi`, cross-KB fanout) → multihop orchestration for multi-hop questions (`agent/tools/multihop.py`, wiki gating navigation in `wiki/`, offline entity bridge index in `entity_index/`) → reflection loop (rewrite query and re-retrieve while insufficient, capped by `RAG_REFLECT_ROUND_CAP`) → rerank trim to `RAG_FINAL_TOP_K` → streamed answer + structured `sources`. Sync IO (Qdrant/embedding/rerank) is wrapped in `asyncio.to_thread`.

**Dual-database split**: PostgreSQL (`rag` schema) is the business source of truth — knowledge bases/folders/documents/parent-child chunks/sessions/messages; vectors live only in Qdrant, one collection per KB (`kb_{id.hex}_v1`, dense + sparse named vectors, auto-created on first write). Parent-child chunking (small-to-big): level 1 parent chunks (2000 chars) → level 0 leaf chunks (400 chars / 80 overlap); **only level-0 leaves go into Qdrant**; hits trace back to parent/document for fuller context. Document ingest: `service/rag/document.py` + `utils/file_ingest.py`, `content_hash`-based versioning with gray-release cleanup of old vector points.

**Permissions**: knowledge base visibility (`private/department/public`) + user department `data_scope`, enforced server-side (invisible and nonexistent KBs return identical messages). RBAC tables under `sys` schema (`routers/system/`, `service/system/`).

## OpenSpec workflow

Spec-driven development via OpenSpec: source-of-truth specs in `openspec/specs/`, in-flight change proposals in `openspec/changes/` (skills under `.qoder/skills/openspec-*`). When changing behavior of a spec'd capability, keep the spec and any in-flight change artifacts (`proposal.md`, `design.md`, `tasks.md`) consistent with the code.
