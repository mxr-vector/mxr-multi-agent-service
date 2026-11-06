# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

## Overview

`multi-agent-service` is a FastAPI HTTP service with four business domains:

- **Agentic RAG** — hybrid retrieval, reflection, rerank, multihop (`readme/RAG.md`)
- **Story AI workspace** — AI script writing → character portraits → keyframe storyboards → material export (`readme/STORY.md`)
- **Draw** — AI diagram-drawing workflow (`readme/DRAW.md`)
- **RBAC** — users/roles/depts/menus/dicts plus runtime model & parameter config

It does **not** load models directly — inference is decoupled behind HTTP to a local vLLM server (or any OpenAI-compatible API) serving chat, embedding, multimodal, image- and video-generation models. There is no offline mode. The companion frontend lives in `multi-agent-ui/` (Vue 3 + Element Plus + pnpm).

Code comments, docs, and commit messages are in Chinese (conventional-commit prefixes with Chinese subjects) — follow that convention. DB schemas are in `database/sql/` (PostgreSQL ≥ 18, uses built-in `uuidv7()`); apply the schema scripts there (`system_schema.sql` / `base_seed.sql`, `rag_schema.sql`, `draw_schema.sql`, `story_schema.sql`, plus `*_alter_*.sql` migrations).

## Commands

Package management uses **uv** (Python >= 3.13; the README's `3.12` refers to the separate vLLM deployment). Default package index is the Tsinghua mirror (configured in `pyproject.toml`).

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

There is **no test framework or linter configured** (frontend only has prettier). Modules carry `if __name__ == "__main__"` blocks used as manual smoke tests — e.g. `uv run python agent/tools/rag_tools.py`. Any entry point that bypasses the FastAPI lifespan (demos, smoke blocks) must first load the config snapshot — `CFG.load_blocking()` in sync context, `await CFG.load()` inside an event loop — otherwise model factories raise "配置快照尚未加载" (see `main.py`).

## CodeGraph

This repo is indexed by CodeGraph (`.codegraph/` exists at the repo root). Before grep/find or reading files to locate or understand code, use the `codegraph_explore` MCP tool (or shell `codegraph explore "<symbols or question>"`) — one call returns verbatim line-numbered source plus call paths and blast radius, which you can Edit from directly.

## Environment configuration (required before running)

`utils/env.py` exposes a singleton `ENV` that reads `APP_ENV` (default `development`) and loads `env/.env.{APP_ENV}`, raising `FileNotFoundError` if missing. Only `env/.env.sample` is committed — copy it to `env/.env.development` first. External service hosts: append `env/host.txt` to `/etc/hosts`.

- Access config via `ENV.<property>` (e.g. `ENV.server_port`). Add settings as `@property` on `ENV_CONFIG` backed by `self.require(...)` so missing keys fail loudly. Never call `os.getenv` in feature code.
- Uploads: `UPLOAD_DIR` (default `data/`) is mounted at `{BASE_URL}/public/files` **without auth** (so `<img>`/video tags work); `UPLOAD_MAX_SIZE_MB` / `VIDEO_UPLOAD_MAX_SIZE_MB` bound sizes.
- Feature flags: `WIKI_ENABLED`, `AGENTIC_TOOLS_ENABLED`, `ENTITY_INDEX_ENABLED`.
- **Config is two-track**: deployment-level settings (postgres/qdrant connection, `EMBEDDING_*`, JWT, auth) stay in env files — embedding model config is pinned because switching models invalidates the vector store. Runtime-tunable settings live in DB and are read through the config snapshot `CFG` (`core/config_snapshot.py`), refreshed on write with last-known-good fallback (frontend「模型管理 / 参数管理」pages, no restart):
  - Model role set comes from dict `model_types` (seeded: `chat`, `rewrite`, `visual`, `rerank`, `image`, `video`); access as `CFG.<role>` (dynamic `__getattr__`), never hardcode a role list. The `image` role's `extra` holds `size`/`quality` defaults (dictionary-driven options `image_size` / `image_quality`); the `video` role's `extra` holds `resolution`/`ratio`/`duration` defaults (`video_resolution` / `video_ratio`).
  - RAG params: `CFG.rag_candidate_pool_size`, `rag_final_top_k`, `rag_reflect_round_cap`, `rag_max_hops`, `rag_hop_pool_size`, `rag_multihop_merge_pool`; chat checkpoint TTL and history limits.
- `ENV.is_prod` is true when `APP_ENV` is `prod` or `production`; `infer.py` refuses to start with reload in prod.

## Architecture

**Entry point** is `infer.py::create_app()`. The `lifespan` startup sequence is load-bearing: `CFG.load()` (fail-fast) → then `asyncio.gather` of independent startup work (concurrent to shorten cold start):
- **required (fail-fast)** — `DocumentService().reset_stale_reindexing()` and `open_checkpointer()`; failure aborts startup.
- **guarded (warn only)** — stale-generating resets for chat / draw / story (`reset_stale_generating*` rewrites orphaned `generating` rows after a crash) and `sync_sse_event_dict()`.

Then checkpoint TTL cleanup runs once and a daily background loop starts (`start_ttl_task`); shutdown resets `chat_graph` and closes the checkpointer. `main.py` is not the web service.

**Auto router registration** (`core/auto_import.py`): recursively scans the `routers` package for any module exposing a module-level `router: APIRouter` and mounts it under a parent prefixed with `ENV.base_url`. To add an endpoint group, create `routers/<area>/<name>.py` with `router = APIRouter(prefix=...)` — no manual registration. The codebase uses namespace packages with **no `__init__.py`** files. Existing groups: `/chat`, `/rag/*`, `/draw`, `/story`, `/system/*`, `/common/file`.

**Middleware chain** (outer→inner): `CORSMiddleware` → `RequestIDMiddleware` (UUID into `request_id_ctx` ContextVar, returned as `X-Request-ID`) → `AccessLogMiddleware` (outside auth so 401s are logged) → `TokenAuthMiddleware` (requires `Authorization: Bearer <API_SECRET_KEY>` or a JWT, except `EXCLUDE_PATHS` and `/public*` / `/static*` path segments; SSE clients may pass the token via `?token=`). Note `add_middleware` uses `insert(0)`: the last-added middleware is outermost, so the add order in `create_app` is reversed relative to this chain.

**Unified response + errors**: handlers return via `utils/response.py::R` (`R.success(data=...)` / `R.fail(msg=..., code=...)`), producing `{code, msg, data}`. `exception/gobal_exception.py::register_exception` converts `HTTPException`, `RequestValidationError`, `AssertionError`, and unhandled exceptions into that shape — raising these is the intended error path. Business exceptions use `exception/bad_except.py::bad_except`.

**Streaming**: long AI operations use SSE via `utils/stream_runtime.py` (`sse_frame`, `spawn_side_task`) and the `SseEvent` enum in `agent/constants/enums/chat.py` (`think` / `answer` / `done` / `error`). Sync IO (Qdrant/embedding/rerank/disk) is wrapped in `asyncio.to_thread`. In-flight generation tasks are tracked in per-domain in-memory registries plus DB status, so restarts can reset stale rows.

**Logging** (`utils/logger.py`): import the shared loguru `logger`; it injects `request_id` into every record and writes rotated dated files under `logs/`. Prefer it over `print`.

**Layering** (strict): `routers/` (HTTP) → `service/` (business logic, one package per domain: `rag/`, `draw/`, `story/`, `system/`, `common/`) → `database/` (CRUD per schema: `rag/`, `draw/`, `story/`, `system/`) plus `agent/` (LangGraph orchestration: `graph/` parent graphs, `tools/`, `prompts/`, `skills/`, `checkpoints/`) and `model/` (provider clients behind factories). Entities mirror schemas under `entity/`.

### Model access — factories only

`model/{chat,embeddings,rerank,compression,visual,sparse,image,video}` each expose a factory; business code never imports concrete clients or passes provider/model names:

- **Chat**: `model/chat/factory.py::build_chat_model()` rebuilds per call from `CFG.chat` so hot-updated config takes effect next request. `model/visual/factory.py` builds the multimodal model for image understanding.
- **Embeddings**: `EmbeddingFactory.get_client()` resolves `EMBEDDING_PROVIDER` (spec: `openspec/specs/embedding/spec.md`); every client subclasses `BaseEmbeddingClient` returning pure vectors (`embed_documents` preserves input order, `embed_query` returns one vector); provider quirks stay encapsulated in adapters; optional capabilities raise `NotImplementedError` on the base class. Cohere is registered but deprecated (incompatible SDK) — keep it registered. `model/embeddings/langchain_adapter.py` is the bridge when LangChain integration is needed; prefer official SDK clients over LangChain wrappers.
- **Image**: `model/image/factory.py::generate_image()` calls OpenAI-compatible endpoints — no reference images → `images.generate`; with references → `images.edit` for a single reference, multi-image `images.generate` + `extra_body` for multiple references (keyframe multi-character consistency), each with fallback. `output_format=webp` / `output_compression=80` are code constants (disk-sensitive story assets); `size`/`quality` default from `CFG.image.extra`, callers may override.
- **Video**: `model/video/factory.py` wraps asynchronous video synthesis and auto-selects the upstream protocol from `CFG.video.api_url` — DashScope/MaaS hosts use the native video-synthesis SDK path, other endpoints (aggregators such as `https://tokenrhythm.studio/v1`) use the gateway's `POST {base}/videos/generations` + `GET {base}/videos/{id}` JSON API (`extra.video_protocol` can force either). Keyframes are downscaled/re-encoded to JPEG before base64 inlining to stay under request-body limits.

### RAG pipeline (Agentic)

Question flow: `agent/graph/chat_graph.py` (LangGraph parent graph, module-level singleton `chat_graph`, lazy-compiled; checkpointer `agent/checkpoints/postgres.py` persists multi-turn state keyed by `thread_id = session_id`; TTL cleanup task; history falls back to `rag.chat_messages` business table) → the chat model autonomously calls the `knowledge_base_search` tool (`agent/tools/rag_tools.py`) in a tool-calling loop → inside the tool: hybrid recall (dense + jieba BM25 sparse, server-side RRF fusion via `agent/tools/document.py::hybrid_retrieve_multi`, cross-KB fanout) → multihop orchestration for multi-hop questions (`agent/tools/multihop.py`, wiki gating navigation in `wiki/`, offline entity bridge index in `entity_index/`) → reflection loop (rewrite query and re-retrieve while insufficient, capped by `RAG_REFLECT_ROUND_CAP`) → rerank trim to `RAG_FINAL_TOP_K` → streamed answer + structured `sources`.

**Dual-database split**: PostgreSQL (`rag` schema) is the business source of truth — knowledge bases/folders/documents/parent-child chunks/sessions/messages; vectors live only in Qdrant, one collection per KB (`kb_{id.hex}_v1`, dense + sparse named vectors, auto-created on first write). Parent-child chunking (small-to-big): level 1 parent chunks (2000 chars) → level 0 leaf chunks (400 chars / 80 overlap); **only level-0 leaves go into Qdrant**; hits trace back to parent/document for fuller context. Document ingest: `service/rag/document.py` + `utils/file_ingest.py`, `content_hash`-based versioning with gray-release cleanup of old vector points.

### Story pipeline (剧本工坊)

Project is the aggregate root; the user-level character library is the cross-project visual-asset base. Tables (`story` schema): `story_projects`, `story_sessions`, `story_messages`, `story_generation_tasks`, `story_scripts` (versioned, single `is_current`), `story_characters`, `story_character_arts`, `story_keyframes`, `story_keyframe_characters`, `story_project_assets` (casting), `story_export_packages`, `story_videos`.

**Script generation** (`routers/story/generation.py` + `service/story/generation.py` + `agent/graph/story/graph.py`):
- Business layer owns SSE framing, write ordering, mutual exclusion and persistence; the graph owns AI orchestration (system-prompt assembly, generation model, tool loop, budget guard, skill audit). Keep this split — the service must not know model/tool details.
- Graph: single `compose` node, **no checkpointer** (each generation is independent; history is injected into the system prompt from business tables). The model must call `skill_read` (see `agent/skills/loader.py`) to read each style's `SKILL.md` before writing, then `references/*.md|txt` on demand — progressive disclosure, read-only, path/suffix guarded. It caps tool rounds, rejects rounds that skip the skill read once, and forces a no-tool finish past the cap. Story-specific overrides: `max_tokens=32768`, stall timeout 300s, empty-output retry.
- Dual-track output contract (`agent/prompts/story.py`, parsed by `service/story/contract.py`): readable script text plus a trailing `<<<STORY_CARDS>>> ... <<<END_STORY_CARDS>>>` JSON block containing `characters` + `keyframes` (+ params). Tolerant parsing (code fences, trailing commas, missing markers) degrades to script-only — never raises. A regex fallback extracts `【关键帧 场次-镜头】` lines from the script body.
- Writes: `story_generation_tasks` (pending) → user message (params snapshot) → assistant placeholder (`generating`) → terminal status. Mutual exclusion is double: session-level in-memory registry + project-level in-flight task check.
- Styles are registered in `agent/skills/loader.py::STYLE_REGISTRY` (`generic` 通用短剧, `shangmeiying` 上美影动画, `handdrawn` 手绘日记) binding a skill package, aspect-ratio presets, and the exact readable-file whitelist injected into the prompt. Skill packages live in `agent/skills/<skill>/`; never execute their scripts or read outside the package.

**Asset sedimentation** (`service/story/sediment.py`, `service/story/character.py`, `service/story/art.py`): message cards can be saved as script versions, saved into the user-level character library (new or merge by name, auto-register casting), turned into keyframes (single or all), or used to launch portrait generation. Character portraits are stored under `UPLOAD_DIR/story/characters/<user_id>/<name>/` (user-id namespace prevents cross-tenant enumeration); keyframes under `story/keyframes/<project>/<keyframe>/`; all paths go through `service/story/storage.py` guards (path traversal, extension whitelist, atomic sequence files).

**Keyframe image generation** (`service/story/keyframe.py`): assembles the positive prompt from the five-part shot description + bound cast (appearance + per-shot state) + reference portraits, then calls `generate_image(reference_images=...)`. Runs as tracked async tasks; **per-project concurrency cap `MAX_CONCURRENT_KEYFRAME_TASKS = 5`**, graceful rejection beyond it, `stop` / `stop-all` endpoints release the mutex, manual image upload/replacement supported. Status flow: `draft → generating → done / failed` (`archived` excluded from export).

**Export & video** (`service/story/export.py`, `service/story/video_plan.py`, `service/story/video.py`, `service/story/video_generation.py`): export packages snapshot current script + casting + selected keyframes immutably, then stream a standardized ZIP (Chinese directory layout + `manifest.json`). Videos have two sources (`story_videos.source`): `upload` (external clips/long cuts, auto first-frame cover) and `generated` (one chapter → one clip). `video_plan.py` parses the current script's `第N集` headings and `【关键帧 场次-镜头】` markers, replaces markers with the chapter's keyframe images in place, and composes one editable chapter prompt (`GET /story/projects/{id}/video-plan`); submitting it once per chapter sends **all available** chapter keyframe images as reference images (`media:[{type:"reference_image"}]` for wan3, one image falls back to first-frame) and creates one `story_videos` row with `episode_no=chapter_no` and all keyframe ids in `generation_params`. Status flow `queued → generating → done/failed/cancelled`, project concurrency cap, startup reset. Each clip is downloaded individually (`GET /story/videos/{id}/download`) for external assembly — there is no in-app whole-film merge.

### Draw pipeline

`routers/draw/diagram.py` + `service/draw/diagram.py` + `agent/prompts/draw.py` implement AI diagram (draw.io/mermaid) generation and editing with SSE; stale `generating` rows are reset at startup like the other domains. Design in `readme/DRAW.md`.

### Permissions

Knowledge base visibility (`private/department/public`) + user department `data_scope`, enforced server-side (invisible and nonexistent KBs return identical messages). Story data is scoped by owning user (character library) and project ownership. RBAC tables under `sys` schema (`routers/system/`, `service/system/`).

### Frontend

`multi-agent-ui/` is Vue 3 + TypeScript + Vite + Element Plus + Pinia + `md-editor-v3` (story script editing) + Mermaid. API wrappers mirror backend domains under `src/api/{aichat,common,draw,rag,story,system}`; routes in `src/router/index.ts` (story: `story/projects`, `story/projects/:id`, `story/character`). Story project detail is panel-based (`ScriptPanel`, `KeyframePanel`, `VideoGenPanel`, `CastingPanel`, `ExportPanel`, `VideoPanel`, `OverviewPanel`) with a right-side AI drawer (`components/ai/AiDrawer.vue`). Menus/permissions come from the backend `sys_menu` tree (dynamic routing).

## OpenSpec workflow

Spec-driven development via OpenSpec: source-of-truth specs in `openspec/specs/`, in-flight change proposals in `openspec/changes/` (skills under `.qoder/skills/openspec-*`). When changing behavior of a spec'd capability, keep the spec and any in-flight change artifacts (`proposal.md`, `design.md`, `tasks.md`) consistent with the code. Currently in flight: `story-ai-workspace`, `story-ia-refactor`, `llm-wiki-multihop-navigation`, `rag-benchmark-refresh`.
