# Jojoba Economic Advisor — Build Guide & Cheatsheet

How the RAG was **upgraded in place** with 14 advanced features, made modular, and
wired so the agent, `/ask`, chat, and the email/n8n paths all use it — behind your
existing two-tier cache. This guide is the end-to-end build: read top to bottom to
understand it, or follow §2 to rebuild it from scratch in the right order.

> Nothing here is a "new RAG". `src/services/rag.py` (a 1,600-line monolith) became
> the package `src/services/rag/`. The public API is unchanged — every
> `from src.services.rag import query_rag, initialize_rag, build_index, …` still
> resolves — so callers didn't move. What changed is *inside*: the query core now
> runs the full feature pipeline, and the monolith is now one module per concern.

---

## 0. Mental model

```
                       ┌──────────── HTTP ────────────┐
  routes/agent/*   routes/chat_routes   routes/n8n_routes   routes/webhook_user
        │                  │                   │                    │
        └───────┬──────────┴─── ask_agent ─────┘                    │
                │            (LangGraph supervisor)                 │
                ▼                                                   ▼
         rag_node ──► query_rag ─────────────────────────►  answer_stream (SSE)
                          │                                         │
                          ▼                                         ▼
        ┌──────────────────────────── src/services/rag/ ───────────────────────┐
        │  TIER-1 exact cache ─► TIER-2 semantic cache ─► _answer_pipeline:     │
        │    rewrite → hybrid(BM25+dense)+metadata+adaptive_k → rerank →        │
        │    compress → versioned prompt (A/B/canary) → generate → groundedness │
        │    → prettify → store BOTH caches → metrics                           │
        └──────────────────────────────────────────────────────────────────────┘
             uses: prompts/registry.py (versioning) · observability/tracing.py
```

Key idea: **the two-tier cache wraps the whole upgraded answer.** A repeat/similar
question returns the finished, formatted, grounded answer without touching the LLM.

---

## 1. Package layout (one module per concern)

```
src/services/rag/
  __init__.py        Public facade — re-exports the original API + the new entrypoints.
  config.py          All constants, read from Settings (single source of truth).
  types.py           RetrievedChunk (decoupled from LlamaIndex).
  # ---- foundation (extracted verbatim from the monolith) ----
  cache.py           TTLLRUCache + SemanticCache (two-tier) — UNCHANGED behaviour.
  metrics.py         Metrics counter.
  embeddings.py      setup_embeddings() / setup_llm().
  chunking.py        chunk_documents_by_type() + per-file-type strategies.
  vector_store.py    setup_vector_store() + dense_search()/all_documents() (new).
  # ---- the 14 features (new modules) ----
  query_transform.py  Query rewriting.
  retrieval.py        Hybrid BM25+dense, metadata filter, adaptive top_k, fusion,
                      retrieve_advanced() (+ its own retrieval cache).
  reranker.py         Cross-encoder reranking (FastEmbed) + lexical fallback.
  compressor.py       Context compression (sentence-level, query-cosine).
  groundedness.py     Hallucination / groundedness check.
  streaming.py        SSE streaming (meta → token → done).
  indexer.py          Incremental indexing (content-hash diff).
  evaluation.py       Automated retrieval eval (hit-rate, MRR, A/B compare).
  formatting.py       prettify_answer() — light, deterministic Markdown tidy.
  # ---- orchestrator ----
  engine.py           Globals/locks, init, build, run_eval, get_rag_status, and the
                      UPGRADED query_rag_sync / query_rag / answer_stream.

Cross-cutting (outside the package because they aren't RAG-only):
  src/prompts/registry.py       Prompt versioning · A/B · canary  (features 10–12).
  src/observability/tracing.py  OpenTelemetry setup + @traced      (feature 9).
  src/middleware/*              Request-ID context + security headers.
```

---

## 1b. Project-wide modularization (same pattern applied to the other monoliths)

The three long service files are now packages; every long module was moved into a
package **verbatim** (AST-extracted) with a facade `__init__.py` that re-exports the old
public names, so no importer changed. The moderate service files (`email_sender` 567,
`history_manager` 331, `user_queries` 301, `email_manager` 281, `n8n_manager` 273,
`chat_manager` 184, `validator` 99) are each already single-responsibility and are kept as
one file on purpose — splitting a cohesive 250-line module would add indirection, not clarity.

```
src/services/agent/            (was agent.py, 1,854 lines)
  __init__.py     Facade — ask_agent, initialize_agent, get_agent_status, batch_processor, …
  util.py         _utcnow (tz-aware).
  config.py       MAX_CONTEXTS / CONTEXT_TTL_HOURS / MAX_AGENT_STEPS — now from Settings.
  models.py       Pydantic models + ConversationContext.
  state.py        EntityExtractor + AgentState (LangGraph schema).
  conversation.py AgentMetrics + ConversationManager (+ singleton).
  nodes.py        supervisor/guard/greeting/gratitude/rag/queue/analyst nodes + router.
                  rag_node calls the upgraded, cached query_rag and uses its answer.
  graph.py        build_economic_advisor_graph.
  email_render.py Markdown → newspaper HTML (escape-first, FIX #10).
  email_processor.py BatchEmailProcessor (+ singleton).
  runtime.py      init, _build_response, ask_agent, get_agent_status, globals/locks.

src/services/question_manager/ (was question_manager.py, 822 lines)
  __init__.py     Facade — full queue/generation/log API (+ DATA).
  data_loader.py  load_data_files() + the shared read-only DATA snapshot.
  queue.py        queue ops (get/add/remove/archive/reset + sync wrappers).
  generation.py   generate-from-data, de-dup, n8n/LLM generation, fallbacks.
  logs.py         question logs (record / query / stats / export).
```

Settings usage: the agent's tunables were scattered `os.getenv` calls; they now live in
`Settings` (`MAX_CONVERSATION_CONTEXTS`, `CONTEXT_TTL_HOURS`, `MAX_AGENT_STEPS`) and are read
through `get_settings()` in `agent/config.py`.

---

## 2. Build order (create files in THIS sequence)

Bottom-up: nothing imports something built later.

**Layer A — Settings & primitives**
1. `src/config/settings.py` — typed `Settings(BaseSettings)` + `get_settings()`. Every
   flag/threshold/model name lives here and comes from `.env`.
2. `src/utils/crypto.py` — `SecretBox` (Fernet) for encrypting user secrets at rest.
3. `src/utils/ownership.py` — `scope_filter()` / `assert_owner()` for per-user isolation.

**Layer B — RAG foundation** (`src/services/rag/`)
4. `config.py` → `types.py` → `cache.py` → `metrics.py` → `embeddings.py`
   → `chunking.py` → `vector_store.py`.
   These are the pieces the monolith already had; each is now importable on its own.

**Layer C — the 14 features**
5. `query_transform.py`, `reranker.py`, `compressor.py`, `groundedness.py`,
   `streaming.py`, `evaluation.py`, `formatting.py` (all leaf modules), then
6. `retrieval.py` (imports the leaves) → exposes `retrieve()` and `retrieve_advanced()`.
7. `indexer.py`.

**Layer D — cross-cutting**
8. `src/prompts/registry.py` — seed v1 (your prompts) + v2 (prettier). 
9. `src/observability/tracing.py` — `setup_tracing(app)`, `@traced`.

**Layer E — orchestrator + facade**
10. `engine.py` — wire the pipeline into the cached, retried query core. **Build last.**
11. `__init__.py` — re-export the public API.

**Layer F — wire the app**
12. `src/services/agent.py` → `rag_node` calls `query_rag(...)` and uses its answer.
13. `src/routes/chat_routes.py` → stream endpoint imports `answer_stream` from the package.
14. `src/main.py` → `setup_tracing(app)`, middleware, include chat/n8n/webhook routers,
    create indexes at startup.

---

## 3. The request lifecycle (what actually happens)

1. A route calls `ask_agent(question, language, user_id, …)`.
2. LangGraph supervisor routes: greeting/gratitude → guard → **rag_node**.
3. `rag_node` calls `await query_rag(question, language=…, bucket_key=user_id)`.
4. `query_rag_sync` (in `engine.py`):
   - validate → `initialize_rag()`
   - **TIER-1 exact cache** hit? return it.
   - **TIER-2 semantic cache** hit (cosine ≥ threshold)? promote to exact, return it.
   - miss → `_answer_pipeline()` inside the retry/backoff loop:
     `retrieve_advanced` (rewrite→hybrid→rerank→compress) → `select_prompt` (v2, sticky
     per user) → `llm.complete` → `prettify_answer` → `check_groundedness`.
   - store the finished answer in **both** caches; record metrics; return
     `{answer, sources, groundedness, prompt_version, rewritten_query, …}`.
5. `rag_node` puts that answer into `analysis_result` (+ recommendations + groundedness).
   Because both `retrieved_context` and `analysis_result` are set, the supervisor
   **skips the analyst** (no redundant second synthesis) and ends.
6. If retrieval found nothing, `rag_node` sets only the context → the analyst runs as a
   **fallback**, exactly as before. Nothing regresses to "no answer".

---

## 4. Each feature — what / where / how to toggle

All flags are in `.env` → `Settings` → `rag/config.py`. Flip a flag, restart; no code change.

| Feature | Module | Flag |
|---|---|---|
| Hybrid search (BM25+dense) | `retrieval.py` (`BM25`, `_weighted_fuse`) | `HYBRID_ENABLED`, `HYBRID_ALPHA` |
| Metadata filtering | `retrieval.py` (`where=` + BM25 `allowed`) | pass `filters=` |
| Adaptive top_k | `retrieval.py` (`adaptive_top_k`) | `ADAPTIVE_TOP_K` |
| Cross-encoder rerank | `reranker.py` | `RERANK_ENABLED`, `RERANK_MODEL`, `RERANK_TOP_N` |
| Query rewriting | `query_transform.py` | `QUERY_REWRITE_ENABLED` |
| Context compression | `compressor.py` | `COMPRESSION_ENABLED` |
| Groundedness check | `groundedness.py` | `GROUNDEDNESS_ENABLED`, `GROUNDEDNESS_THRESHOLD` |
| Streaming | `streaming.py` (`answer_stream`) | chat `/stream` endpoint |
| Incremental indexing | `indexer.py` (`incremental_index`) | call it instead of full rebuild |
| Retrieval evaluation | `evaluation.py` | `evaluate_retrieval`, `compare_configs` |
| Observability/tracing | `observability/tracing.py` (`@traced`) | `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Prompt versioning | `prompts/registry.py` | `register(PromptVersion(...))` |
| A/B testing | `prompts/registry.py` (`select`, sticky hash) | `set_weights(name, {...})` |
| Canary deployments | `prompts/registry.py` | `set_weights(name, {'v1':0.9,'v2':0.1})` |

Every stage degrades gracefully: if the cross-encoder can't load, reranking falls back to
lexical overlap; if hybrid returns nothing, the engine falls back to the legacy query
engine; if the embedder fails, the semantic cache silently no-ops.

---

## 5. Caching — preserved, and now covering the upgrade

Two tiers, unchanged from your original design, both in `cache.py`:
- **Exact** (`TTLLRUCache`): SHA-256 of the question → finished answer dict.
- **Semantic** (`SemanticCache`): cosine match against recent question embeddings; a hit
  is promoted into the exact cache so the next identical hit is O(1).

Plus a **retrieval cache** in `retrieval.py` (`_retrieval_cache`, same `TTLLRUCache` class)
keyed on `(query, filters)`, so even a cache-miss answer skips repeat BM25+rerank+compress
when the retrieved context is the same. Rebuilds/incremental indexing call
`invalidate_bm25()` + `clear_query_cache()` so stale context is never served.

---

## 6. Prettier answers (Markdown, AI-assistant style)

Delivered *through* the prompt-versioning feature rather than hard-coding:
- `prompts/registry.py` seeds **v2** = your system prompt + a `<response_format>` block
  (bold lead sentence, `##` subheads, `-` bullets, bolded key numbers, "Bottom line:").
- v2 is rolled out to **100%**; **v1 stays registered at weight 0** for instant rollback:
  `get_registry().rollback("system_en", "v1")` — no redeploy. Canary instead with
  `set_weights("system_en", {"v1":0.9, "v2":0.1})`.
- `formatting.py::prettify_answer()` then does a light, deterministic tidy (spacing, list
  breaks) — it never rewrites content, so it can't hallucinate or reformat numbers.

---

## 7. Newspaper email — now renders the Markdown

`agent.py::_render_article_html()` turns the Markdown answer into email-safe newspaper HTML:
`##` → gold subheads, `-` → bulleted rows, `**bold**` → `<strong>`, drop cap on the first
paragraph (tag-safe, so a bold opener isn't split). **Security invariant preserved (FIX #10):**
each line is HTML-escaped *before* any Markdown translation, so real tags in the content
(`<script>…`) become inert entities while our own markup renders. The n8n path is unchanged:
Schedule → `POST /api/webhook/user/process-next` → backend runs `ask_agent` and sends the
newspaper email, so the user's n8n needs no SMTP.

---

## 8. n8n integration — the honest security boundary

Users paste their n8n API key; we `SecretBox`-encrypt it **at rest** (`crypto.py`) and only
ever return a masked hint. The app deploys/activates a per-user workflow via the n8n REST
API using a per-user webhook JWT. **This is encryption-at-rest, not zero-knowledge:** the
backend must decrypt the key in memory to call n8n on the user's behalf, so an operator with
process access could observe it in use. Don't claim the owner "can never see" it — claim
it's encrypted at rest and never logged or returned. True zero-knowledge would require the
user's n8n to call us with its own credential we never store.

---

## 9. Configuration (`.env`)

`Settings` reads these (see `.env.example` for the full list): `GROQ_API_KEY`,
`EMBEDDING_MODEL`/`EMBEDDING_DIM`, `GROQ_MODEL`, `CHROMA_COLLECTION`, the feature flags in
§4, `ENCRYPTION_SECRET`, `PUBLIC_BASE_URL`, `N8N_DEFAULT_BASE_URL`, `MONGODB_URI`,
`OTEL_ENABLED`/`OTEL_EXPORTER_OTLP_ENDPOINT`. Change behaviour by editing `.env`, not code.

---

## 10. Run, index, evaluate

```bash
pip install -r requirements.txt
cp .env.example .env            # fill GROQ_API_KEY, ENCRYPTION_SECRET, MONGODB_URI, …
python -m src.services.build_index          # first-time full index from data/raw
uvicorn src.main:app --reload               # docs at /docs when DEBUG=true

# incremental re-index after editing data/raw (embeds only changed chunks):
python -c "from src.services.rag import incremental_index; print(incremental_index())"

# ablation: measure a config against a golden set, or A/B two configs:
python -c "from src.services.rag import evaluate_retrieval, retrieve; ..."
```

---

## 11. Verification status (be honest with reviewers)

- ✅ **Syntax**: `python -m compileall src/` passes on every module.
- ✅ **Imports / no circular imports**: all three packages (`rag`, `agent`,
  `question_manager`) import cleanly with the heavy libs stubbed, each preserves its full
  original public API, and a scope-aware linter confirms no undefined names (i.e. no import
  got dropped in the split — a check `py_compile` can't do).
- ⏳ **End-to-end runtime**: needs the real deps (`llama_index`, `chromadb`, `fastembed`,
  `groq`, `motor`) + `.env` + a built index. The pipeline, cache, agent rewire, prompt v2,
  and email renderer were each unit-checked in isolation, but run the eval harness against
  your data before trusting retrieval quality, and smoke-test one `/ask` and one chat
  `/stream` after wiring your keys.

---

## 12. Cheatsheet (reuse elsewhere)

- **Modularize a monolith safely**: move it into a package verbatim (AST-extract functions
  so you don't retype), keep `__init__.py` re-exporting the old names, *then* split and
  upgrade. Callers never notice.
- **Upgrade, don't fork**: put new capability *inside* the function everything already
  calls (`query_rag_sync`), so the whole system benefits and the cache still wraps it.
- **Ship prompts like code**: version them, weight them, roll back by weight — never edit a
  live prompt in place.
- **Escape before you render**: any Markdown→HTML for untrusted text must escape first,
  translate your own markup second.
