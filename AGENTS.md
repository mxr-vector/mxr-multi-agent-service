# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

## Overview

`multi-agent-service` is the inference-serving half of a two-part system (`multi-agent-base` + `vllm_env`). It exposes a FastAPI HTTP service for multi-agent orchestration and embedding utilities. It does **not** load models directly — model inference is decoupled behind HTTP (an OpenAI-compatible vLLM server serving chat + pooling/embedding models, see `README.md`). There is no offline mode.

## Commands

Package management uses **uv** (Python `>=3.13`; note `README.md`'s `3.12` refers to the separate vLLM deployment). The default package index is the Tsinghua mirror (configured in `pyproject.toml`).

```powershell
uv sync                      # install/lock dependencies
uv run python infer.py       # run the FastAPI service (uvicorn, reload, workers=1)
uv run python main.py        # demo script
uv run uvicorn infer:app --host 127.0.0.1 --port 8000 --reload   # alternative service launch
```

There is **no test framework or linter configured**. Modules like `semantic_search.py` and `mcp_tools/weather.py` carry `if __name__ == "__main__"` blocks used as manual smoke tests — run them directly with `uv run python <path>`.

## Environment configuration (required before running)

The app will not start without an env file. `utils/env.py` exposes a singleton `ENV` that, on first import, reads `APP_ENV` (default `development`) and loads `env/.env.{APP_ENV}`, raising `FileNotFoundError` if it is missing. Only `env/.env.sample` is committed — copy it to `env/.env.development` (or `.env.production`) first.

- Access all config through `ENV.<property>` (e.g. `ENV.server_port`, `ENV.embedding_provider`). Add new settings as `@property` on `ENV_CONFIG` backed by `self.require(...)` so missing keys fail loudly. Do not call `os.getenv` directly in feature code.
- `ENV.is_prod` is true when `APP_ENV` is `prod` or `production`.

## Architecture

**Entry point** is `infer.py::create_app()`, which builds the FastAPI app, mounts `/static`, installs middleware, registers exception handlers, and auto-loads routers. `main.py` is unrelated to the web service (it is an embedding demo).

**Auto router registration** (`core/auto_import.py`): `load_routers` recursively scans the `routers` package for any module exposing a module-level `router: APIRouter` and mounts it under a parent router prefixed with `ENV.base_url` (e.g. `/multi-agent-base`). To add an endpoint group, create `routers/<name>.py` defining `router = APIRouter(prefix=...)` — no manual registration needed. (Note: the codebase uses namespace packages with **no `__init__.py`** files.)

**Middleware chain** (added in `infer.py`, executed outer→inner): `RequestIDMiddleware` → `TokenAuthMiddleware` → `AccessLogMiddleware`.
- `RequestIDMiddleware` sets a UUID into the `request_id_ctx` ContextVar and returns it as the `X-Request-ID` header.
- `TokenAuthMiddleware` requires `Authorization: Bearer <API_SECRET_KEY>` on every request except `EXCLUDE_PATHS` (`/`, `/docs`, `/openapi.json`, `/favicon.ico`, `/static`) and any `/public*` path.

**Unified response + errors**: All handlers should return via `utils/response.py::R` (`R.success(data=...)` / `R.fail(msg=..., code=...)`), producing `{code, msg, data}`. `exception/gobal_exception.py::register_exception` converts `HTTPException`, `RequestValidationError`, `AssertionError`, and unhandled `Exception` into that same shape — so raising these is the intended error path.

**Logging** (`utils/logger.py`): import the shared `loguru` `logger`. It is patched to inject `request_id` from the ContextVar into every record, writing dated files under `logs/` (info + separate error log, with rotation/retention). Prefer this over `print`.

### Embedding subsystem (`model/embeddings/`)

This is the most-developed module and follows a strict, spec-driven design (see `openspec/specs/embedding/spec.md`). Rules to preserve when editing:

- **Configuration-driven**: provider and model come only from `EMBEDDING_PROVIDER` and `EMBEDDING_MODEL_NAME`. Public methods must **not** accept a `model_name` argument.
- **Factory-only access**: business code obtains a client via `EmbeddingFactory.get_client()` (`factory.py`), which resolves `EMBEDDING_PROVIDER` through the `EmbeddingProvider` enum against an internal registry. Never import a concrete client (`OpenAIEmbeddingClient`, etc.) directly.
- **Unified interface**: every client subclasses `BaseEmbeddingClient` (`clients/base.py`) and returns pure vectors — `embed_documents(docs) -> List[List[float]]` (input order preserved) and `embed_query(query) -> List[float]`. Provider-specific quirks (output unwrapping, `text_type`, result ordering) stay encapsulated inside each adapter.
- **Optional capabilities** (e.g. `embed_multimodal`) default to raising `NotImplementedError` on the base class; only providers that support them override.
- Cohere is registered but **deprecated** (SDK incompatible with the current API) — keep it registered for future re-enablement.

### Known stale references

None currently. (Historical note: `main.py` and the removed `state/PGVectorManager.py` once imported `model.embeddings.client`, which was refactored into `clients/` + `factory.py`; those references have been cleaned up. Use `EmbeddingFactory.get_client()` for embedding access.)

## OpenSpec workflow

This repo is set up for spec-driven development via **OpenSpec** (`openspec/` + skills under `.codex/skills/` and the `openspec-*` Skill tools). Active change proposals live in `openspec/changes/`, the source-of-truth specs in `openspec/specs/`. When making behavioral changes to a spec'd capability (currently `embedding`), keep the spec and any in-flight change artifacts (`proposal.md`, `design.md`, `tasks.md`, `specs/`) consistent with the code.
