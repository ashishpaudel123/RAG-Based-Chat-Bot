# RAG Chatbot — Nepal Citizenship Assistant / Customer Service (Gemini)

A web-based, retrieval-augmented conversational AI chatbot that answers questions **only from an approved
knowledge base**, shows the sources behind every answer, and falls back safely when it has no evidence.
A *domain profile* selects the knowledge domain: `nepal_citizenship` (default; implements the
*Nepal Citizenship RAG Knowledge Base Specification*) or `customer_service` (the original store demo).

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
| Multilingual understanding | One LLM call per message detects the language (Nepali, Roman Nepali, English, mixed), normalizes the query into Nepali + English search queries, extracts intents and the user's facts (age, parents' nationality, district…), and decides whether a clarifying question is needed; plus a spelling/romanization dictionary (`nagrikta` → `नागरिकता`) |
| Hybrid retrieval | Vector search + BM25 keyword search over every query variant, reciprocal-rank fusion, filters (only *verified* sources; only *current* law unless the question is historical; other districts' local practice excluded) and reranking by authority tier, currentness, district and law-vs-local preference |
| Legal answer engine | Clarifying questions only when facts change the answer (at most once in a row); structured answer contract (Short answer, Your situation, Rule, Documents, Procedure, Where to apply, Fees/time, Legal source, Last verified, Important); law vs procedure vs local practice vs inference kept apart; replies in the user's language; validator flags any fee, section number or duration not found in the evidence; confidence level (HIGH/MEDIUM/LOW/NEEDS_CLARIFICATION) stored per answer |
| Source metadata & versioning | YAML front matter or admin form: source type, authority tier, section, jurisdiction/district, status (current/superseded/historical), effective dates, official URL, last verified, verification status. New versions supersede old ones, which are kept for historical questions; pending documents are never used for answers |
| Evaluation | Gold question set (language, noise level, intent, expected sources, expected facts, must-not-claim); Recall@k, Precision@k, MRR, nDCG, citation accuracy, fact coverage, LLM-judged groundedness/hallucination, unsupported-claim rate, intent/clarification/language accuracy, latency; per-language and per-noise breakdown; no-RAG baseline; reproducible config recorded with every run |

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

Inside the backend, one message goes through (`backend/app/services/rag.py`):

```
query analysis (language, normalized ne+en queries, intents, facts, district, time, law/local)  ── 1 LLM call
   └─ facts missing that change the answer? → ask ≤3 clarifying questions (no retrieval)
vector search (1 embedding call for all query variants)  +  BM25 keyword search with synonym expansion
   → filters: verified only · current (or historical when asked) · not another district's local practice
   → reciprocal-rank fusion → rerank by authority tier × currentness × district × law/local preference
   → relevance gate (similarity threshold or keyword coverage) → evidence pack with full source metadata
grounded generation with the answer contract                                                ── 1 LLM call
   → citation/claim validator (fees, sections, durations must appear in the evidence) → confidence
```

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
      rag.py            hybrid retrieval, fusion, reranking, answer contract, fallback, confidence
      query_analysis.py language/intent/fact extraction, normalized queries, clarification decision
      keyword_index.py  BM25 keyword index (cached, rebuilt when the knowledge base changes)
      normalization.py  Devanagari/Roman tokenizer, language detection, synonym expansion
      answer_validation.py  citation and fee/section/duration claim checks
      document_metadata.py  front-matter parsing and source-metadata validation
      profile.py        domain profile loader (app/profiles/*.json)
      memory.py         history window + rolling summary
      chat.py           orchestrates one chat turn and persists messages/citations
      knowledge.py      ingest, update, delete, re-index
    cli.py              create-admin / ingest / reindex commands
  tests/                pytest suite (runs offline)
frontend/               Next.js 16 + TypeScript + Tailwind CSS
  src/app/              / (chat), /login, /register, /admin
  src/components/       chat sidebar, message bubble with sources & feedback, auth form
  src/lib/              typed API client, auth context
evaluation/             question sets + evaluation harness (RAG vs. baseline)
knowledge_base/         Nepal citizenship knowledge records (template + README)
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
python -m app.cli ingest ../knowledge_base   # your citizenship records (or ../sample_data with DOMAIN_PROFILE=customer_service)

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
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | generation model (rolling alias). Flash-Lite has much higher free-tier limits than Flash (e.g. 500 vs 20 requests/day). Run `python -m app.cli list-models` to see the models your key can use, and pin one for reproducible evaluations |
| `GEMINI_FALLBACK_MODELS` | `gemini-flash-latest` | comma-separated models tried in order when the main model is overloaded (503), out of quota (429) or unavailable; empty disables failover |
| `GEMINI_EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `gemini-embedding-001` / `768` | embedding model and size (run a full re-index after changing) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `200` | characters per chunk and overlap |
| `TOP_K` | `5` | candidates retrieved per query |
| `RELEVANCE_THRESHOLD` | `0.55` | minimum cosine similarity for a chunk to count as evidence |
| `MAX_CONTEXT_CHUNKS` | `4` | evidence chunks sent to Gemini |
| `DOMAIN_PROFILE` | `nepal_citizenship` | `nepal_citizenship`, `customer_service`, or a path to your own profile JSON (assistant name, intents, fact fields, clarification policy, suggestions, localized messages, synonym dictionary — see `backend/app/profiles/`) |
| `QUERY_ANALYSIS` | `true` | LLM query analysis (language, normalization, intents, facts, clarification). `false` falls back to a heuristic + follow-up rewriting |
| `CLARIFYING_QUESTIONS` | `true` | allow the assistant to ask for missing facts before answering |
| `CANDIDATE_POOL` / `RRF_K` | `20` / `60` | candidates per retriever and the rank-fusion constant |
| `KEYWORD_MIN_COVERAGE` | `0.5` | share of query terms a keyword-only match must contain to count as evidence |
| `QUERY_REWRITE` | `true` | rewrite follow-up questions (only used when `QUERY_ANALYSIS=false`) |
| `HISTORY_MESSAGES` / `SUMMARY_TRIGGER_MESSAGES` | `8` / `20` | memory window and when older turns are summarised |

**Free tier:** each chat message uses 1 embedding + 2 generation requests (query analysis + answer); a clarifying question uses only 1. Set `QUERY_ANALYSIS=false` to save one request per message at the cost of multilingual understanding. Quota errors are not retried on the same model; the app fails over to the next model, and document indexing waits out per-minute embedding limits. Check usage at <https://aistudio.google.com/rate-limit>.

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
| POST | `/api/documents/upload` | Upload knowledge document (multipart: `file`, `title`, `tags`, optional metadata fields `source_type`, `authority_tier`, `legal_reference`, `district`, `validity_status`, `effective_from`, `source_url`, `last_verified`, `verification_status`, …; front matter is read automatically) | admin |
| GET | `/api/documents/{id}` · `/chunks` | Document details / indexed chunks | admin |
| PUT | `/api/documents/{id}` | Update title/tags/metadata (no re-embedding unless the title changes) or upload a new version (old one becomes `superseded`) | admin |
| DELETE | `/api/documents/{id}` | Remove a document and its vectors (deleting the current version restores the previous one) | admin |
| POST | `/api/knowledge/reindex` | Re-index everything or one document (`{"document_id": ...}`) | admin |
| GET | `/api/knowledge/runs` | Index-run history (configuration used) | admin |
| GET | `/api/admin/users` · PATCH `/api/admin/users/{id}` | Manage users (role, active) | admin |
| GET | `/api/admin/stats` · `/api/admin/logs` | Usage metrics / operational errors | admin |
| GET | `/api/health` | Health check | public |
| GET | `/api/profile` | Assistant name, tagline and suggested questions of the active domain profile | public |

## Nepal citizenship knowledge base

Knowledge records live in `knowledge_base/` — one Markdown file per topic with a YAML front-matter block
(see [`knowledge_base/_TEMPLATE.md`](knowledge_base/_TEMPLATE.md) and [`knowledge_base/README.md`](knowledge_base/README.md)).

```bash
cd backend && python -m app.cli ingest ../knowledge_base   # records start as "pending"
```

Review each record against its official source, then mark it **Verified** in Admin → Knowledge base
(or set `verification_status: verified` before ingesting). Only verified, current records are used for
answers; superseded versions are kept for historical questions. Put district-specific office practice in
separate records with `district:` set. Restart the backend after large CLI imports so the vector store is
reloaded.

## Evaluation

The harness indexes a corpus (with its front-matter metadata) into an isolated store, runs a gold question
set through the full pipeline **and** a no-RAG baseline, and writes `results.json` + `report.md` to
`evaluation/results/<timestamp>/`.

```bash
cd backend && source .venv/bin/activate && cd ..
# Nepal citizenship gold set (format: evaluation/questions_citizenship.example.json)
GEMINI_API_KEY=... python evaluation/run_eval.py --corpus knowledge_base --questions evaluation/questions_citizenship.json
# store demo set, quota-friendly
GEMINI_API_KEY=... python evaluation/run_eval.py --no-judge --no-baseline --delay 5
python evaluation/run_eval.py --provider fake                     # offline smoke test of the harness
```

Question fields: `question`, `language` (ne/en/roman_ne/mixed), `noise_level`, `expected_intent`,
`expected_sources` (record ids or file names; empty = unanswerable), `expected_answer_facts`,
`must_not_claim`, optional `expect_clarification`. Add `--include-pending` to test unverified records and
`--limit N` for a quick run.

| Metric | How it is measured |
|---|---|
| Recall@k · Precision@k · MRR · nDCG@k | expected source documents in the reranked candidate list |
| Current-version accuracy | cited evidence is current law (for non-historical questions) |
| Fact coverage | expected answer facts present in the answer |
| Citation accuracy | share of cited sources that are expected sources |
| Groundedness / hallucination rate | LLM judge: are all claims supported by the evidence? |
| Unsupported-claim rate | answers where the validator flagged a fee/section/duration not in the evidence |
| Must-not-claim violations | answers containing a forbidden (wrong or invented) claim |
| Unanswerable handled safely · false fallbacks | fallback/clarification vs. grounded answers |
| Intent · clarification · reply-language accuracy | from the query analysis and the answer |
| Latency | mean / p50 / p95 |

Every metric is also reported per question language and noise level. Each run records models, chunking,
fusion and threshold settings, prompt version, question-set version and corpus (proposal §4.6).

## Testing

```bash
cd backend && python -m pytest -q          # 51 tests, offline (fake provider, SQLite)
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/chatbot_test python -m pytest -q
cd frontend && npx eslint src && npm run build
```

The tests cover validation, parsing and chunking, auth and RBAC, conversation ownership, grounded answers
with citations, fallback behaviour, feedback, document update/re-index/delete, controlled errors when the
model API fails, rate limiting, prompt-delimiter sanitisation, front-matter metadata and the verification
gate, versioning and restore, schema upgrades, language detection and normalization, Roman-Nepali to
Devanagari keyword matching, authority/currentness/district reranking, clarification, and the claim validator. CI runs them on every push
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
