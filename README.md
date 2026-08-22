# Data Q&A — Ask questions about your spreadsheets in plain English

Upload one or more CSV/Excel files and ask analytical questions in natural language.
The app answers with a number, a chart, and **the exact SQL it ran** so you can verify it.

Built for the Forward Deployed Engineer take-home. Runs entirely on **open-source models**
— locally via Ollama, or hosted via Groq.

---

## The core idea: the model writes SQL, it never does the math

The naive approach — paste rows into a prompt and ask the LLM for a total — hallucinates.
LLMs are unreliable calculators and files get big fast.

So this app uses **text-to-SQL over DuckDB**:

```
question ─► LLM (schema only) ─► SQL ─► guardrail ─► DuckDB executes ─► real numbers
                                                          │
                                             ┌────────────┴────────────┐
                                             ▼                         ▼
                                     chart auto-selected      LLM explains the RESULT
```

Two consequences that matter:

1. **Correctness.** Every number is computed by a SQL engine, not predicted by a model.
   The LLM only *translates* the question and *explains* the result it is handed.
2. **Cost & privacy.** Only the compact schema enters the prompt — never the data rows.
   Token cost per question is roughly constant whether your file has 100 rows or 100 million.

---

## What it does

| Acceptance criterion | How it is met |
|---|---|
| **Multi-file upload** | Many files per session. Each CSV → one table; **each Excel sheet → its own table**. Also reads JSON/NDJSON (nested objects flattened) and Parquet. |
| **Cross-file analysis** | Join keys are auto-detected at upload and fed to the model, so questions spanning files become SQL `JOIN`s. Totals, averages, filters, comparisons and trends are all pushed down to DuckDB. |
| **Visual insights** | The chart type is chosen from the *shape* of the result set (KPI / bar / line / scatter / table) — no extra model call. |
| **Delta solutioning** | See below. |

### Delta solutioning — the engineering on top of "call an LLM"

1. **Self-correcting SQL loop** — when generated SQL fails, the DuckDB error is fed back
   to the model and it retries (bounded, default 3). This is the difference between a demo
   that breaks on the first odd column name and one that holds up.
2. **Read-only guardrails** — every query is parsed with `sqlglot` and rejected unless it is
   a single read-only `SELECT`. Filesystem/network functions (`read_csv_auto`, `read_parquet`,
   `glob`, …) are blocked by name, *and* DuckDB itself runs with `enable_external_access=false`.
   Defence in depth: a model-written `SELECT * FROM read_csv_auto('/etc/passwd')` is stopped twice.
3. **Auto join-key detection** — column name + dtype match, scored by real value overlap.
   This is what makes cross-file questions work without the user explaining relationships.
4. **Auditability** — the generated SQL is shown with every answer. In an enterprise, a number
   you cannot trace is worthless.
5. **Honest failure** — if the data cannot answer the question, the model returns a
   `CANNOT_ANSWER` sentinel and the UI says so plainly instead of inventing a figure.
6. **Schema-RAG** — with many/wide tables, only the tables and columns relevant to the question
   are sent (join keys always retained), so prompt size stays bounded at enterprise scale.
7. **PII masking + schema-only mode** — sample rows are masked (emails, phones, long IDs) before
   they ever reach a hosted model, and `SCHEMA_ONLY=true` sends *no* data values at all.
8. **Type coercion at ingest** — date-looking text columns become real timestamps, so trend
   questions actually work (without this, `strftime` fails at the binder).
9. **Pluggable SQL generation** — `SQL_GENERATOR=langchain` runs the generation step as a
   LangChain LCEL chain over the same providers. A test asserts both paths return identical
   SQL, rows and charts: the framework owns prompt assembly, never correctness or cost control.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 15 (App Router, TS), Tailwind, Recharts | Fast, typed, React-native charting |
| Backend | FastAPI (Python 3.12) | Async, typed request/response via Pydantic |
| Query engine | **DuckDB** (in-process) | Reads CSV/Excel natively, real SQL, zero infrastructure |
| SQL safety | `sqlglot` | Parse-level validation, not regex guessing |
| Orchestration | Explicit pipeline (LangChain LCEL optional) | Bounded and debuggable by default; framework path available via config |
| Model (local) | **Qwen2.5-Coder 7B** via Ollama | Open-source, strong at SQL, data never leaves the machine |
| Model (hosted) | **Llama 3.3 70B** via Groq | Open-source, fast, free tier |

---

## Run it locally

### Option A — Docker Compose (everything, including the local model)

```bash
docker compose up --build
```

Then pull the model once:

```bash
docker compose exec ollama ollama pull qwen2.5-coder:3b
```

Open <http://localhost:3000>.

### Option B — run the two services directly

**Backend**

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate       # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                  # then set a model backend (below)
uvicorn app.main:app --reload --port 8000
```

**Frontend** (in a second terminal)

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open <http://localhost:3000>.

### Pick a model backend

You need **one** of these. `LLM_BACKEND=auto` (the default) tries local first, then hosted.

**Local — nothing leaves your machine:**

```bash
ollama pull qwen2.5-coder:3b
```

Ollama serves on `127.0.0.1:11434` and the app finds it automatically. Verify the
offline path end to end, with every answer checked against a pandas ground truth:

```bash
python tests/local_ollama_check.py
```

Measured on a CPU-only 15W laptop (i5-1345U, no discrete GPU): **6/6 correct, ~20s
per question** — including a cross-file join, a `strftime` monthly trend, and an
honest refusal. The first call is slower while the model loads into RAM. With a GPU,
or with `qwen2.5-coder:7b`, expect better accuracy on unusual joins.

> **Windows + WSL:** install Ollama on **Windows**, not inside WSL, unless you have a
> GPU you want to pass through. Ollama binds to loopback only, so an instance inside
> the WSL VM is not reachable from a backend running on Windows without setting
> `OLLAMA_HOST=0.0.0.0` in WSL and pointing `OLLAMA_URL` at the VM's address. If you
> do run the backend inside WSL, install Ollama there too and keep both on loopback.

**Hosted — free key from <https://console.groq.com>:**

```bash
GROQ_API_KEY=gsk_...
```

---

## Deploying

| Piece | Where | Notes |
|---|---|---|
| Frontend | Vercel | Set `NEXT_PUBLIC_API_URL` to the deployed backend URL |
| Backend | Render / Fly / any Docker host | Set `GROQ_API_KEY`, `LLM_BACKEND=groq`, and `CORS_ORIGINS` to your Vercel origin |

Hosted model runtimes cannot run Ollama, which is exactly why the provider is an
abstraction — the same image runs local or hosted on a config flag.

---

## Tests

```bash
cd backend
.venv/Scripts/python.exe tests/test_pipeline.py
```

15 tests covering the parts that must be right regardless of which model is plugged in:
guardrails (12 blocked / 3 allowed), the self-correction retry loop, honest failure,
retry exhaustion, cross-file joins, chart selection, bounded multi-turn context,
schema-only privacy mode, PII masking, native-vs-LangChain parity, SQL extraction across
model output styles (fenced, `<think>` blocks, prose preamble), and that provider errors
always name a cause. They use a scripted mock LLM, so they are deterministic and need no
API key — a reviewer can verify correctness before configuring any model.

The happy-path test asserts the returned numbers **equal a pandas ground truth** — the
point being that correctness comes from the engine, not the model.

[VERIFICATION.md](VERIFICATION.md) records a full end-to-end run from a clean clone:
all eight acceptance-criteria questions, the same question answered identically by a
120B hosted model and a 3B local one, prompt-size measurements, and the safety checks.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /session` | Start a session |
| `POST /upload` | Multipart upload (`session_id` + repeated `files`) → schema + detected joins |
| `GET /schema/{id}` | Current schema |
| `POST /ask` | `{session_id, question}` → answer, SQL, rows, chart spec, attempts |
| `GET /config` | Active model backend + privacy settings (never returns secrets) |
| `PUT /settings` | Change non-secret runtime settings (privacy mode, model backend) |
| `DELETE /session/{id}` | Destroy session and its data |

### Supported file types

`.csv` `.tsv` `.txt` · `.xlsx` `.xls` (each sheet becomes a table) · `.json` `.ndjson` `.jsonl`
(nested objects flattened to dotted columns) · `.parquet`

The app is schema-agnostic — it introspects whatever columns arrive, so any *tabular* data works.

### Credentials

API keys live in the server environment and are **never** exposed to the browser or settable
through the API. `GET /config` reports only whether a backend is *available* (a boolean), never
the key. The UI settings panel adjusts non-secret knobs only: model backend and privacy mode.

---

## Security & privacy posture

- **Local mode: data never leaves the machine.** Hosted mode: only schema, masked samples
  and the question transit — **raw files never leave your infrastructure**.
- **Read-only sandbox:** single `SELECT` only, no filesystem/network access from SQL,
  statement timeout, row cap on results.
- **Session isolation:** one in-memory DuckDB per session, TTL-expired, destroyed on demand.
  Nothing is persisted to disk.
- **Cost guard:** a per-session token budget hard-stops runaway usage. Retries are bounded and
  there is no open-ended agent loop.
- **Audit log:** every `question → SQL → status` is logged for traceability.
- Secrets come from the environment; `.env` is git-ignored.

---

## Scaling notes / known limitations

- **Single worker.** Session state (DuckDB connections) lives in-process, so run the backend
  with `--workers 1`. The production path is Redis for session metadata plus file-backed
  DuckDB on shared storage — `SessionStore` is the only class that changes.
- **Memory-bound.** Files are held in memory; very large files should be spilled to a
  file-backed DuckDB database instead.
- Excel formulas are read as their computed values; macros are never executed.
- Join detection is a heuristic surfaced as *hints* — the model still decides.

## What I'd build next

Streaming answers, a saved-question/dashboard view, a proper eval suite run in CI against a
labelled question set, semantic-embedding schema retrieval (the current one is lexical), and
row-level access control for multi-tenant use.
