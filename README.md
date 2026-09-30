# Customer Service Chatbot (RAG + Gemini)

A web-based, retrieval-augmented conversational AI chatbot that answers questions **only from an approved
knowledge base**, shows the sources behind every answer, and falls back safely when it has no evidence.

This repository implements the system proposed in the *Project-VI Proposal Report "Customer Service Chatbot"*
(Himalayan WhiteHouse International College, Purbanchal University): a Python/FastAPI backend, a Next.js +
TypeScript + Tailwind frontend, Gemini for generation and embeddings, ChromaDB for vector search and
PostgreSQL for application data.

[Architecture](#architecture) · [Quick start](#quick-start) · [API](#api-endpoints) · [Evaluation](#evaluation)

---

## Features

| Area | What is implemented |
|---|---|
| Chat | Multi-turn conversations, chat history sidebar, rename/delete, suggested questions, loading / empty / error / retry states, mobile layout |
| RAG | Parse → clean → chunk (+ metadata) → embed → index; query rewriting for follow-ups; top-K vector search; relevance threshold; de-duplication; grounded prompt with numbered sources |
| Grounding | Answers cite sources as `[n]`; expandable source cards (document, section/page, similarity, snippet); safe fallback when evidence is missing or the model reports insufficient evidence |
| Memory | Recent-message window plus a rolling LLM summary of older turns |
| Knowledge management | Admin upload (PDF, DOCX, TXT, Markdown), metadata (title, tags), versioned replacement, delete, per-document and full re-index, chunk inspection |
| Feedback & monitoring | 👍/👎 with optional comment per answer; admin stats (fallback rate, latency, helpfulness); operational error log; index-run history |
| Security | Server-side Gemini key; JWT auth; RBAC (user/admin); conversation ownership checks; file type/size/magic-byte validation; rate limits on AI and auth endpoints; retrieved text treated as untrusted (delimiter sanitisation + system rules); no prompts or secrets in logs |
| Evaluation | Fixed question set; RAG vs. no-RAG Gemini baseline; retrieval relevance, context precision, correctness, LLM-judged groundedness/hallucination, failure handling, latency; reproducible config recorded with every run |

## Architecture

```mermaid
flowchart LR
  subgraph Offline["Offline knowledge pipeline"]
    A[Approved documents] --> B[Parse & clean] --> C[Chunk + metadata] --> D[Gemini embeddings] --> E[(ChromaDB)]
  end
  subgraph Online["Online chat pipeline"]
    U[User] --> F[Next.js frontend] --> G[FastAPI backend]
    G --> M[Conversation memory] --> R[Retriever]
    R -- query embedding --> E
    R -- evidence ≥ threshold --> L[Gemini API]
    R -- no evidence --> FB[Safe fallback]
    L --> G
    G <--> P[(PostgreSQL)]
  end
```

Online flow for one message (proposal Figure 1.4): **validate request → load history → build retrieval
query → search vector DB → evidence sufficient?** → *yes:* grounded prompt → Gemini → answer with sources ·
*no:* fallback / ask to clarify. Nothing is stored if Gemini fails, so the user can simply retry.

### Repository layout

```
backend/                FastAPI application
  app/
    main.py             app setup, CORS, security headers, admin bootstrap
    config.py           all settings (env vars), incl. RAG parameters
    models.py           ER model: User, Conversation, Message, Citation, Feedback, Document, Chunk, ErrorLog, IndexRun
    routers/            auth, chat, documents/knowledge, feedback, admin, health
    services/
      llm.py            Gemini service (generation + embeddings, retries) and offline fake provider
      document_processing.py  validation, parsing (PDF/DOCX/MD/TXT), cleaning, chunking
      vector_store.py   ChromaDB wrapper (cosine similarity)
      rag.py            retrieval, evidence filtering, prompt construction, fallback
      memory.py         history window + rolling summary
      chat.py           orchestrates one chat turn and persists messages/citations
      knowledge.py      ingest, update, delete, re-index
    cli.py              create-admin / ingest / reindex commands
  tests/                pytest suite (runs offline)
frontend/               Next.js 16 + TypeScript + Tailwind CSS
  src/app/              / (chat), /login, /register, /admin
  src/components/       chat sidebar, message bubble with sources & feedback, auth form
  src/lib/              typed API client, auth context
evaluation/             question set + evaluation harness (RAG vs. baseline)
sample_data/            sample knowledge base for a fictional electronics store
docker-compose.yml      PostgreSQL + backend + frontend
```

## Quick start

### Option A — Docker Compose (PostgreSQL + backend + frontend)

```bash
cp .env.example .env          # set GEMINI_API_KEY, JWT_SECRET, ADMIN_EMAIL/ADMIN_PASSWORD, POSTGRES_PASSWORD
docker compose up --build
```

Open <http://localhost:3000>, sign in with the admin account from `.env`, open **Admin dashboard** and
upload documents (or the files in `sample_data/`). Load the sample knowledge base from the command line with:

```bash
docker compose cp sample_data backend:/app/sample_data
docker compose exec backend python -m app.cli ingest /app/sample_data
```

### Option B — Local development

Requirements: Python 3.11+, Node.js 20+, a [Gemini API key](https://aistudio.google.com/apikey).

```bash
# Backend (http://localhost:8000, API docs at /docs)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env               # set GEMINI_API_KEY, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
uvicorn app.main:app --reload       # creates tables and the admin account on first start
python -m app.cli ingest ../sample_data   # optional: load the sample knowledge base

# Frontend (http://localhost:3000)
cd ../frontend
npm install
cp .env.example .env.local         # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Local runs use SQLite by default; set `DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/chatbot`
to use PostgreSQL. Without an API key you can try the whole application with `LLM_PROVIDER=fake`
(a deterministic keyword-based stand-in used by the tests — not a real language model; lower
`RELEVANCE_THRESHOLD` to about `0.2` when using it).

## Configuration

All settings are environment variables (see `.env.example` and `backend/app/config.py`). The RAG parameters
that matter most for quality:

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` | generation model |
| `GEMINI_EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `gemini-embedding-001` / `768` | embedding model and size (run a full re-index after changing) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `200` | characters per chunk and overlap |
| `TOP_K` | `5` | candidates retrieved per query |
| `RELEVANCE_THRESHOLD` | `0.55` | minimum cosine similarity for a chunk to count as evidence |
| `MAX_CONTEXT_CHUNKS` | `4` | evidence chunks sent to Gemini |
| `QUERY_REWRITE` | `true` | rewrite follow-up questions into standalone search queries |
| `HISTORY_MESSAGES` / `SUMMARY_TRIGGER_MESSAGES` | `8` / `20` | memory window and when older turns are summarised |

Tune `RELEVANCE_THRESHOLD` with the evaluation harness: too high causes false fallbacks, too low lets
irrelevant chunks through.

## API endpoints

Interactive documentation: <http://localhost:8000/docs>.

| Method | Endpoint | Purpose | Access |
|---|---|---|---|
| POST | `/api/auth/register` | Register user | public |
| POST | `/api/auth/login` | Authenticate user (returns JWT) | public |
| GET | `/api/auth/me` | Current user | user |
| POST | `/api/chat` | Send a chat message (new or existing conversation) | user |
| GET | `/api/chats` | List user chats | user |
| POST | `/api/chats` | Create an empty conversation | user |
| GET | `/api/chats/{id}` | Read a conversation (messages, sources, feedback) | owner |
| PATCH | `/api/chats/{id}` | Rename conversation | owner |
| DELETE | `/api/chats/{id}` | Delete conversation | owner |
| POST | `/api/feedback` | Submit / update feedback on an answer | owner |
| GET | `/api/documents` | List knowledge documents | admin |
| POST | `/api/documents/upload` | Upload knowledge document (multipart: `file`, `title`, `tags`) | admin |
| GET | `/api/documents/{id}` · `/chunks` | Document details / indexed chunks | admin |
| PUT | `/api/documents/{id}` | Update title/tags or upload a new version | admin |
| DELETE | `/api/documents/{id}` | Remove document and its vectors | admin |
| POST | `/api/knowledge/reindex` | Re-index everything or one document (`{"document_id": ...}`) | admin |
| GET | `/api/knowledge/runs` | Index-run history (configuration used) | admin |
| GET | `/api/admin/users` · PATCH `/api/admin/users/{id}` | Manage users (role, active) | admin |
| GET | `/api/admin/stats` · `/api/admin/logs` | Usage metrics / operational errors | admin |
| GET | `/api/health` | Health check | public |

## Evaluation

The harness indexes a corpus into an isolated vector store, runs the fixed question set in
`evaluation/questions.json` (20 answerable + 6 unanswerable/adversarial questions over `sample_data/`)
through the RAG pipeline **and** a direct Gemini baseline without retrieval, and writes
`results.json` + `report.md` to `evaluation/results/<timestamp>/`.

```bash
cd backend && source .venv/bin/activate && cd ..
GEMINI_API_KEY=... python evaluation/run_eval.py                 # full run with LLM judge + baseline
python evaluation/run_eval.py --no-judge --no-baseline --delay 2  # cheaper / quota-friendly
python evaluation/run_eval.py --provider fake                     # offline smoke test of the harness
```

| Metric | How it is measured |
|---|---|
| Retrieval relevance | expected source document among retrieved evidence (hit rate) |
| Context precision | share of evidence chunks that come from the expected document |
| Answer correctness | expected key facts present in the answer |
| Groundedness / hallucination rate | Gemini-as-judge: are all claims supported by the evidence? |
| Failure handling | unanswerable questions answered with a fallback or without unsupported claims |
| Latency | mean / p50 / p95 end-to-end time |

Every run records the models, chunking, top-K, threshold, prompt version, question-set version and corpus
so results are reproducible (proposal §4.6). Report failure cases alongside improvements rather than
assuming RAG is always better (§5.3).

## Testing

```bash
cd backend && python -m pytest -q          # 28 tests, offline (fake provider, SQLite)
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/chatbot_test python -m pytest -q
cd frontend && npx eslint src && npm run build
```

The tests cover validation, parsing and chunking, auth and RBAC, conversation ownership, grounded answers
with citations, fallback behaviour, feedback, document update/re-index/delete, controlled errors when the
model API fails, rate limiting and prompt-delimiter sanitisation. CI runs them on every push
(`.github/workflows/ci.yml`).

## Security notes

- The Gemini key and JWT secret live only in server environment variables; the browser only talks to the
  backend. The backend refuses to start in `ENVIRONMENT=production` with the default JWT secret.
- Retrieved chunks are wrapped in `<source>` blocks with delimiter tags neutralised, and the system prompt
  tells the model to treat them as data, never instructions. This reduces, but cannot fully eliminate,
  prompt-injection risk — only index trusted, approved documents.
- Uploads are limited by extension, size (10 MB), magic bytes and UTF-8 checks, and stored under random names.
- The rate limiter is in-process; use a shared store such as Redis if you run several backend replicas.
- The JWT is kept in `localStorage` for simplicity; for production consider httpOnly cookies with CSRF protection.

## Limitations and future work

As stated in the proposal: RAG reduces but cannot guarantee zero hallucinations, and voice, autonomous
actions and multimodal input are out of scope. Natural next steps are Nepali/multilingual support, hybrid
keyword + semantic retrieval, re-ranking, streaming responses, an analytics dashboard with continuous
evaluation, human hand-off/ticketing and multi-provider failover.

The sample documents describe a **fictional** store ("Himal Electronics") created for demonstration and
evaluation only.
