# Atlas — DarGlobal & Wasalt Property Assistant

A retrieval-augmented chatbot for English and Arabic property research, with filters,
project questions, comparisons, citations and browser-persisted conversations.

## Approach

1. **Collect:** Discover public pages through sitemaps, links and supported pagination.
   The resumable collector respects robots rules, rate-limits requests and optionally
   renders pages with Playwright or extracts PDF text. Save observations to
   `data/raw/` as CSV with source URLs, methods, timestamps and fetch status.
2. **Process:** Normalize and deduplicate records, extract property attributes and
   preserve unknown values. Export normalized CSV to `data/processed/`, then build
   structured SQLite records and an FTS5 passage index.
3. **Retrieve:** Use an LLM-generated, validated filter plan for exact SQL constraints
   on location, property type, budget, currency and rental period. Retrieve evidence
   with lexical/BM25 search and optional multilingual embeddings.
4. **Answer:** Give the LLM a bounded evidence bundle and source IDs. Instructions
   require supported claims and explicit unknowns; citation IDs are validated. Model
   failures fall back to structured results or source excerpts.

## Models

| Component | Model | Role |
| --- | --- | --- |
| Planning and generation | [OpenRouter `openrouter/free`](https://openrouter.ai/openrouter/free) | Remote filter extraction and answer synthesis. The underlying free LLM varies; an explicit `:free` ID and optional free fallback are configurable. |
| Optional semantic retrieval | [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) | Local Sentence Transformers model producing 384-dimensional normalized vectors, using `query:` / `passage:` prefixes and cosine similarity. |

No fine-tuning is performed. NumPy stores the embedding index; no separate vector
database is needed. Dense retrieval supplements general knowledge questions without
a location scope. Structured searches and selected-property comparisons retrieve
from matching records directly.

Local setup enables embeddings to improve paraphrase and cross-language retrieval.
**Docker and Railway default to `ENABLE_SEMANTIC=0`**, excluding PyTorch and embedding
weights to reduce RAM usage. AI planning and answers remain available; semantic
matching may weaken. The full Docker build remains available with `ENABLE_SEMANTIC=1`.

## Data scope

The bundled snapshot contains **360 records** (50 DarGlobal, 310 Wasalt) and **558
evidence passages**. Of these records, 263 are summaries; 97 come from other retrieved
pages, including projects, articles and indexes. Bundled observations are labeled
`web_retrieval` or `web_index_summary`; the collector supports fresh HTTP, browser
and PDF collection. Coverage is partial; prices and availability require source
confirmation. Refreshing CSV data requires rebuilding the search and embedding indexes.

## Configuration

Local use requires Python 3.10+. Setup creates `.venv`, installs requirements, downloads
embeddings, builds indexes and runs Python tests. Packages and model/browser caches
stay in `.venv`. After setup, add `OPENROUTER_API_KEY` to `.env`. The default chat route
is `OPENROUTER_MODEL=openrouter/free`. Local URL: **http://127.0.0.1:8000**.

Railway builds the root `Dockerfile` from GitHub. The image uses Python 3.11, a non-root
user and Waitress, rebuilding SQLite from CSV during image creation. Configure Railway
with `OPENROUTER_API_KEY`, `OPENROUTER_MODEL=openrouter/free`, `ENABLE_SEMANTIC=0` and
`PORT=8000`; set health check `/healthz` and domain target port `8000`. No hosted database
or persistent volume is required. Credentials, environments and model caches stay
out of Git.

## Commands

```bash
# Local setup; add OPENROUTER_API_KEY to .env after it completes
python3 scripts/setup_local.py
```

```bash
# Start locally with semantic retrieval
.venv/bin/python -m app check-model
.venv/bin/python -m app serve
```

```bash
# Alternative: run without semantic retrieval
ATLAS_BUILD_SEMANTIC=0 .venv/bin/python -m app serve --port 8001
```

```bash
# Refresh data and embeddings; stop the server first
.venv/bin/python -m app crawl --source darglobal --max-pages 250 --delay 2
.venv/bin/python -m app crawl --source wasalt --max-pages 1000 --delay 2
.venv/bin/python -m app embed --model intfloat/multilingual-e5-small
```

```bash
# Regression checks
.venv/bin/python -m unittest discover -s tests -v
node --test tests/test_history.cjs
```

```bash
# Alternative: run the lightweight Docker image
ENABLE_SEMANTIC=0 docker compose up --build -d
```

```bash
# Verify a running local server, or replace the URL with the deployed address
python3 scripts/smoke_test.py --url http://127.0.0.1:8000 --ai
```

```bash
# Stop the Docker service
docker compose down
```
