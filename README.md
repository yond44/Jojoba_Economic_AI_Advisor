# Jojoba Economic Advisor — Backend

AI-powered economic analysis API. Answers market and economic questions from a curated knowledge base using a multi-agent RAG pipeline, and dispatches scheduled newspaper-style email briefings through n8n automation.

**Live demo:** [jojobanews.vercel.app](https://jojobanews.vercel.app/)

## Architecture

```
                        ┌──────────────────────────────────────┐
                        │            React Frontend            │
                        │        (Vercel, EN/ID locale)        │
                        └──────────────────┬───────────────────┘
                                           │ REST + JWT
                        ┌──────────────────▼───────────────────┐
                        │           FastAPI Backend            │
                        │                                      │
   ┌────────────┐       │  ┌─────────┐  ┌────────────────┐     │
   │    n8n     │◄──────┼──┤ Webhook │  │  LangGraph     │     │
   │ (schedules,│       │  │ routes  │  │  Agent Graph   │     │
   │  triggers) │──────►│  └─────────┘  │  ┌──────────┐  │     │
   └────────────┘       │               │  │ Validator│  │     │
                        │               │  │ Retriever│  │     │
   ┌────────────┐       │               │  │ Answerer │  │     │
   │   SMTP /   │◄──────┼───────────────┤  │ Reviewer │  │     │
   │   Email    │       │               │  └──────────┘  │     │
   └────────────┘       │               └───────┬────────┘     │
                        │                       │              │
                        │  ┌──────────┐  ┌──────▼─────────┐    │
                        │  │ MongoDB  │  │ ChromaDB (RAG) │    │
                        │  │ (users,  │  │ + FastEmbed    │    │
                        │  │ history, │  │ + Groq LLM     │    │
                        │  │ queue)   │  └────────────────┘    │
                        │  └──────────┘                        │
                        └──────────────────────────────────────┘
```

**Query flow:** question → topic validation → RAG retrieval (ChromaDB + BGE embeddings) → LLM answer generation (Groq) → self-review loop with retry → response with sources and follow-up recommendations.

**Briefing flow:** n8n schedule → webhook endpoint → question queue → batch agent processing → HTML email rendering → SMTP dispatch → delivery history logging.

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI, Uvicorn |
| Agent orchestration | LangGraph, LangChain Core |
| LLM | Groq (Llama models) |
| RAG | LlamaIndex, ChromaDB, FastEmbed (BGE-small) |
| Database | MongoDB (Motor, async) |
| Auth | JWT (PyJWT), bcrypt, API keys for services |
| Automation | n8n workflows (included in `n8n/workflows/`) |
| Deployment | Docker, Hugging Face Spaces (prebuilt index strategy) |

## Getting started

### Prerequisites

- Python 3.11+
- MongoDB running locally (or a connection string)
- A [Groq API key](https://console.groq.com/)

### Local development

```bash
# 1. Clone and install
git clone <repo-url> && cd jojoba-economic-advisor
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

# 2. Configure environment
cp .env.example .env
# edit .env — at minimum set GROQ_API_KEY and SECRET_KEY

# 3. Build the vector index (one-time, or when data/raw changes)
python -m src.services.build_index

# 4. Run
uvicorn src.main:app --reload
```

API docs are available at `http://localhost:8000/docs` when `DEBUG=true`.

### Docker

```bash
docker compose up --build
```

This starts the API on `:8000` and n8n on `:5678`. Import the workflows from `n8n/workflows/` into the n8n editor to enable scheduled briefings.

## Design decisions & trade-offs

**Prebuilt index for free-tier deployment.** Hugging Face Spaces' free tier has tight memory and cold-start limits. Instead of embedding documents at startup (slow, OOM-prone), the ChromaDB index is built offline with `build_index.py` and committed via Git LFS. A content hash of `data/raw/` skips rebuilds when source documents haven't changed.

**Keyword topic validation.** Incoming questions are gated by a word-boundary keyword validator before touching the LLM. An LLM-based classifier would be more accurate, but the keyword gate is zero-latency and zero-cost — the right trade-off for free-tier infrastructure. Off-topic questions never consume LLM quota.

**Self-review agent loop.** Generated answers pass through a reviewer node that can reject and retry (up to `MAX_RETRIES`). This costs extra LLM calls but measurably reduces hallucinated or off-topic answers reaching users.

**In-memory rate limiting.** Per-client limits live in process memory. This is sufficient for a single-instance deployment; scaling horizontally would require moving to Redis — a known, documented limitation rather than premature infrastructure.

## Project structure

```
├── src/
│   ├── main.py               # App factory, startup pipeline, route registration
│   ├── auth/                 # JWT + API-key authentication
│   ├── config/               # Settings, database connection + indexes, prompts
│   ├── db/                   # User persistence layer
│   ├── middleware/            # Error handling, request logging, rate limiting
│   ├── models/               # Pydantic schemas
│   ├── routes/               # API endpoints (agent, auth, users, emails, history)
│   ├── services/             # Agent graph, RAG, validators, email, queue managers
│   └── utils/                # Security, logging, HTML email rendering
├── data/raw/                 # Source documents for the knowledge base
├── n8n/workflows/            # Importable n8n automation workflows
├── tests/                    # Pytest unit tests
├── .github/workflows/ci.yml  # Lint + test on every push/PR
├── Dockerfile                # Non-root, healthcheck, layer-cached build
└── docker-compose.yml        # API + n8n stack
```

## API overview

All endpoints are prefixed with `/api/v1` and require a JWT bearer token unless noted.

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/n8n-token` |
| Agent | `POST /agent/ask`, `POST /agent/batch-email`, `GET /agent/history`, `GET /agent/stats`, `GET /agent/search` |
| Questions | queue management for scheduled briefings |
| Emails | recipient CRUD (global + per-user lists) |
| History | sent-briefing delivery history and statistics |
| Webhooks | n8n integration endpoints (`/api/webhook/*`, token-authenticated) |
| Health | `GET /health` (unauthenticated, used by Docker healthcheck) |

Full interactive documentation: run with `DEBUG=true` and open `/docs`.

## Testing & CI

```bash
pytest tests -v        # run the test suite
ruff check src tests   # lint
```

Tests cover the topic validator (including word-boundary regression cases), password hashing, ObjectId serialization, and rate limiting. CI runs both on every push and pull request via GitHub Actions.

## Security notes

- Secrets live in `.env` only — never committed (`.gitignore` enforced). Rotate any key that has ever been shared.
- Internal exception details are never returned in HTTP responses; errors are logged server-side and clients receive generic messages.
- Passwords hashed with bcrypt (12 rounds); accounts lock after repeated failed logins.
- API docs and the OpenAPI schema are disabled when `DEBUG=false`.

## License

MIT


Azriel = hashing,indexing, emabedding, input vectorDB

-flow data
-directory data

Sinta = retrieval , LLM, get answer. 
- coding aja dulu (tanpa di running)/bikin DB dummy(testing)
- LLM yang dipake dan hasil keluaran data
- json
{
    "question" : "what is crypto?"
    "answer" : "lorem ipsum"
}
Dewi = Prompt, agent. 
{
    isGreetings : False,
    isGratitude: False,
    "question" : "what is crypto?"
    "answer" : "lorem ipsum"
}
Yonda = API



