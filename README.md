# Atlas — DarGlobal & Wasalt property assistant

An interview assignment application: public-data collection, CSV-first processing,
property search, source-grounded OpenRouter answers, browser chat history, and Docker deployment.

## Quick start

Python 3.10+ is required. All local packages and model/browser caches stay in `.venv`.

```bash
python3 scripts/setup_local.py
source .venv/bin/activate
```

Edit `.env` locally. The setup preserves existing credentials:

```dotenv
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openrouter/free
OPENROUTER_FALLBACK_MODEL=
SEMANTIC_MODEL=intfloat/multilingual-e5-small
```

Only the OpenRouter key is required. Get it from https://openrouter.ai/settings/keys.
Keep `.env` private. `openrouter/free` uses free models with variable availability and
quota; an explicit tested `:free` model can be configured for consistent evaluation.
Paid model IDs are rejected. Local embeddings do not require another API key.

```bash
python -m app check-model
python -m app serve
```

Open **http://127.0.0.1:8000**. Restart the server after changing `.env`.
The setup creates `.venv`, installs the three requirements files, builds the CSV
search index, downloads the embedding model, builds its vectors, and runs Python tests.
Use `python3 scripts/setup_local.py --browser` to also download Chromium for collection.
Use `--no-model-download` to defer embedding download/indexing.

To test the deployment's retrieval configuration locally without changing `.env`:

```bash
ATLAS_BUILD_SEMANTIC=0 .venv/bin/python -m app serve --port 8001
```

The embedding code and optional requirements remain in this repository. Downloaded
weights and `.venv` stay out of Git; setup reproduces them on another machine.

## Docker: build, run and verify

Install Docker Desktop or Docker Engine with the Compose plugin. Stop any local
server already using port 8000. Docker creates its own Linux environment; it never
copies or depends on the host `.venv`.

### Default deployment image: semantic search disabled

Both Docker and Compose default to the lightweight image. It keeps structured search,
lexical/BM25 retrieval, citations, OpenRouter planning/answers and browser chat history.
It excludes PyTorch, embedding weights and embedding inference to reduce memory use.
The Docker setting overrides `SEMANTIC_MODEL` from the host `.env`.

```bash
ENABLE_SEMANTIC=0 docker compose up --build -d
docker compose ps
docker compose logs --tail=50 atlas
```

Open **http://127.0.0.1:8000**. In another terminal:

```bash
curl --fail http://127.0.0.1:8000/healthz
.venv/bin/python scripts/smoke_test.py --ai
```

The smoke test verifies HTTP assets, search, cited evidence and a real OpenRouter answer.
It uses Python's standard library and requires no additional package installation.
Check the running image's configuration and resource use:

```bash
docker compose exec -T atlas python -c 'import importlib.util, os; from app import config; assert not os.getenv("SEMANTIC_MODEL"); assert importlib.util.find_spec("torch") is None; print("Semantic search disabled; PyTorch absent.")'
docker stats --no-stream
```

Alternatively, build and run without Compose:

```bash
docker build --build-arg ENABLE_SEMANTIC=0 -t atlas-chatbot .
docker run --rm --name atlas-chatbot --env-file .env \
  -e PORT=8000 -p 127.0.0.1:8000:8000 atlas-chatbot
```

Stop the Compose deployment when finished:

```bash
docker compose down
```

### Optional full image for local evaluation

On a machine with enough RAM, explicitly enable embeddings. This downloads CPU
PyTorch and the embedding model during the build and builds the vector index:

```bash
ENABLE_SEMANTIC=1 docker compose up --build -d
```

The Dockerfile uses a non-root user and Waitress, requires an API key at runtime,
builds SQLite from the raw CSV, and exposes `/healthz`. Full-image weights/vectors are
built into the image. It performs no scraping or first-use model download at startup.
`.dockerignore` excludes host environments, credentials, caches and generated host indexes.

## Railway deployment for the interview demo

Deploy the lightweight Docker image from GitHub. Railway detects the root `Dockerfile`;
no extra deployment configuration file, Docker registry or hosted database is required.
Keep this repository's contents at the GitHub repository root. If it is nested inside
a larger repository, set Railway's service root directory to the directory containing
this Dockerfile.

1. Create an empty GitHub repository for this project.
2. From this directory, stage the code and review the file list:

```bash
git init
git add .
git status --short
```

Verify `.env`, `.venv`, model caches and generated indexes are absent from the staged
files. Include the application, collectors, optional semantic code/requirements, tests,
Docker files and CSV data. Then publish, replacing the repository URL:

```bash
git commit -m "Build Atlas real estate assistant"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/atlas-chatbot.git
git push -u origin main
```

If the folder is already a Git repository, reuse it and its existing remote instead
of reinitializing or adding another remote.

3. In Railway choose **New Project → Deploy from GitHub repo**, select the repository,
   and use your available Trial/Free allowance. A paid plan is not required for this demo.
4. In the web service's **Variables**, set:

```dotenv
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openrouter/free
ENABLE_SEMANTIC=0
PORT=8000
```

The API key is a runtime secret: enter it only in Railway's Variables UI, never in
GitHub, a Docker build argument or source. `ENABLE_SEMANTIC` is a non-secret build
argument declared in the Dockerfile. Leave custom build/start commands empty; the
Dockerfile supplies them. The server listens on `0.0.0.0` and respects `PORT`.

5. Set the service health-check path to **`/healthz`** in **Settings → Deploy**. Deploy
   the pending changes. An initial deployment may fail if the API key was not set yet;
   deploy again after adding the variables.
6. Under **Settings → Networking → Public Networking**, choose **Generate Domain**.
   Use target port **8000** if prompted. Open the generated HTTPS URL.
7. Verify both the public application and a real AI answer:

```bash
.venv/bin/python scripts/smoke_test.py \
  --url https://YOUR-SERVICE.up.railway.app --ai
```

Later commits to the connected branch trigger deployment automatically when GitHub
autodeploy is enabled. After changing code or the collected CSV snapshot:

```bash
git add .
git commit -m "Update Atlas demo"
git push
```

Railway's documented trial is a one-time $5 credit for up to 30 days, with a 1 GB RAM
limit and shared CPU. Services stop when the trial expires or its credit is spent;
the credit does not guarantee 30 days of uptime. Trial services consume resources
while idle. Keep embeddings disabled for this deployment and monitor Usage/Metrics.
Limited Trial accounts restrict outbound networking; test OpenRouter access after
GitHub verification instead of checking only that the page loads.

The search index is reproduced from CSV during image build. Chat histories live in
each visitor's browser, so this demo needs no persistent volume or additional database.
OpenRouter quotas and availability are separate from Railway's hosting allowance.
The final deployment occurs in your Railway account; a working URL exists only after
that deployment succeeds.

Provider references (checked 20 November 2026):

- [Dockerfile builds](https://docs.railway.com/builds/dockerfiles)
- [Deployment health checks](https://docs.railway.com/deployments/healthchecks)
- [Public domains](https://docs.railway.com/networking/public-networking)
- [GitHub autodeploy](https://docs.railway.com/deployments/github-autodeploys)
- [Trial limits and verification](https://docs.railway.com/pricing/free-plan)

## Data collection and provenance

The bundled corpus is **360 searchable records**, not 360 fully detailed properties:

| Content | Count |
| --- | ---: |
| DarGlobal records | 50 |
| Wasalt records | 310 |
| Listing/project summaries | 263 |
| Records from other retrieved pages, including indexes/articles | 97 |
| Evidence chunks | 558 |

`data/raw/pages.csv` preserves 403 original observations and failed retrieval receipts.
`data/raw/index_summaries.csv` contains derived card excerpts whose destination URLs
were established by saved link-resolution attempts. No destination slugs are invented.
`data/processed/` contains the normalized combined/per-source exports, failures and statistics.
These counts can change after you run collection; `stats.json` is authoritative.

Initial implementation-time terminal networking was restricted. The bundled observations
were obtained through public-page research retrieval, saved as raw CSV, and processed
by the included code. They are explicitly labeled `web_retrieval` or `web_index_summary`;
they are not represented as a completed direct HTTP crawl or live inventory.

The executable collector writes `http_html`, `browser_html` or `pdf_text` observations.
It checks crawl policy, restricts hosts/redirects, rate-limits, retries selected transient
failures, follows public links/sitemaps, traverses supported pagination and checkpoints
its queue. It does not sign in, submit leads, bypass access controls, or operate transactions.
Use only within the source's permitted scope and the assignment's authorization.

To expand data, run locally, then rebuild before creating a new image:

```bash
.venv/bin/python -m app crawl --source darglobal --max-pages 250 --delay 2
.venv/bin/python -m app crawl --source wasalt --max-pages 1000 --delay 2
.venv/bin/python -m app embed --model intfloat/multilingual-e5-small
```

Repeat a command to resume its queue. `--refresh` starts fresh discovery; `--max-pages 0`
removes the page-count cap. `--include-arabic` follows Arabic routes. `--browser` enables
optional rendering, and `--urls-file scripts/extra-urls.example.txt` adds verified seeds.
For browser collection, install Chromium through `setup_local.py --browser`.

The next data priority is full detail pages for existing summaries, followed by wider
city/type coverage. No arbitrary record count guarantees quality. Search result caps,
dynamic unit selectors and unverified API filters remain explicit coverage limitations.
Image-only PDFs need an OCR extension. Unknown values remain unknown; source price
anomalies are flagged, not silently corrected. Disappearing listings are not marked sold.

Reproduce the bundled transformation without another network request:

```bash
.venv/bin/python scripts/extract_index_summaries.py
.venv/bin/python -m app ingest
```

Stop the serving process before refreshing data/indexes. Docker deployments use a frozen
snapshot; rebuild/redeploy after collecting new data. Preserve the raw CSV in the repository.

## Architecture and interview explanation

```text
Public pages / sitemaps / links
  -> resumable collector
  -> raw CSV                      first persisted collected data
  -> parsing / normalization
  -> normalized CSV
  -> SQLite records + FTS5 chunks  reproducible search index
  -> validated property filters + lexical retrieval (+ optional local embeddings)
  -> bounded evidence bundle
  -> free OpenRouter model
  -> cited answer / property cards / comparison
```

| Code | Responsibility |
| --- | --- |
| `app/crawl.py`, `htmltools.py` | Public fetching, queue, page/link/JSON parsing |
| `app/extract.py`, `common.py` | Source fields, numbers, Arabic normalization, CSV, provenance |
| `app/ingest.py` | CSV exports, chunking, SQLite/FTS index |
| `app/search.py`, `semantic.py` | Exact filters, lexical/optional dense retrieval |
| `app/openrouter.py`, `chat.py` | Free-only client, validated planning, evidence and fallbacks |
| `app/server.py`, `__main__.py` | WSGI API, Waitress/local serving and CLI |
| `static/` | Customer UI, citations, comparisons and browser-local chat history |
| `scripts/` | Isolated local setup, snapshot transformation and smoke test |
| `tests/` | Python regression/WSGI tests and browser-history unit tests |
| `Dockerfile`, `compose.yaml` | Lightweight deployment by default; optional full semantic build |

Important design choices:

- SQLite handles property search without a database subscription. Chat history is not
  mixed into the rebuildable search index.
- The model produces validated filter JSON, not unrestricted SQL. Price queries keep
  currencies and rental periods separate; missing facts never satisfy numeric filters.
- Website content is evidence, not instructions. Answers cite supplied passages and
  distinguish communities, developments and listings. Citation IDs are checked.
- No prompt or retrieval pipeline guarantees zero hallucinations. Verify grounding
  with manual evaluation before submission, particularly prices and amenity claims.
- New conversation preserves older threads using browser-local storage. History survives
  refresh on the same browser/profile/origin and can be downloaded or deleted. It does
  not synchronize between devices; clearing browser data/private sessions can remove it.
- The customer UI excludes provider labels, API-key instructions, CSV internals and
  diagnostics. Source citations and meaningful data limitations remain visible.
- API keys are server-only; request bodies and concurrency are bounded, cross-origin
  chat requests are rejected, and CSV/debug endpoints are disabled by default.
- OpenRouter outages/quota errors have a clearly worded source-result fallback. Free
  model routing can vary; choose a tested explicit `:free` ID for reproducible demos.

## Testing and final submission

```bash
.venv/bin/python -m unittest discover -s tests -v
node --test tests/test_history.cjs
node --check static/app.js
```

Node is used only for frontend checks, never to run the application. Python tests include
WSGI conformance, health checks, hidden diagnostics, filters, Arabic retrieval, CSV
round trips, semantic-score validation, provider errors and key handling. Browser-history
tests verify reload, separate conversations, deletion and storage-quota behavior.

Before sending the assignment:

- Run the real Docker smoke test with `--ai` and the public HTTPS smoke test.
- Try English/Arabic questions, budget/rental filters, follow-ups and selected-card comparisons.
- Verify source citations, zero-result behavior and refusal to invent live availability.
- Refresh the page and switch between saved conversations on desktop/mobile.
- Confirm no `.env`, `.venv`, credentials or generated machine caches were committed.
- Provide the working URL, repository, setup instructions, data scope/date and limitations.

The agent verified application tests and configuration structure. Docker was unavailable
in the implementation environment, so a successful image build, real container startup
and hosted URL must be verified from your regular terminal/account before submission.

## Developer operations

```bash
.venv/bin/python -m app doctor
.venv/bin/python -m app check-model
```

`requirements.txt` is the small serving dependency set. `requirements-semantic.txt`
adds local embedding dependencies; `requirements-collector.txt` adds Playwright/PDF tools.
The local setup refuses global or user-site installs and stores package/model/browser
caches inside `.venv`. No host Python packages are installed by Docker.
After verifying the container works independently, `.venv` can be removed to reclaim
local packages and model downloads. Keep source, `.env` and CSV data.

Routes: `/healthz`, `/api/status`, `/api/search`, `/api/records/ID`, `/api/chat`.
`ATLAS_DEV_TOOLS=1` explicitly enables local CSV export/diagnostics; leave it off on public
hosting. The CLI exposes developer details without adding them to the customer UI.
