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
10. **Data quality profiling at ingest** — nulls, duplicate rows, constant columns,
    identifier-like columns and numbers-stored-as-text, computed as DuckDB aggregates.
    Surfaced in the sidebar, and the serious ones are given to the model, because
    "this column is 90% empty" changes what a correct answer to a question about its
    average looks like.
11. **Result validation** — the guardrail asks whether SQL is safe to run; this asks
    whether the result means what was asked. An `AVG()` over a mostly-empty column, a
    filter that matched nothing, a `LIMIT` the question never requested — each becomes
    a caveat shown beside the answer, never a reason to hide it.
12. **Confidence from observed facts** — attempts taken, caveats raised, whether the
    schema was narrowed, whether a detected join was relied on. Not the model's opinion
    of itself: models are poorly calibrated about their own output. Three buckets with
    the reasons attached, because a bare score invites false precision.
13. **Ambiguity handling** — "which region is best?" has no single correct SQL. Where one
    reading is clearly intended the app answers and *states the assumption*; where
    several measures are equally plausible it asks, offering each as one click. Lexical
    and pre-LLM, so it costs nothing.
14. **An eval suite, not a vibe** — `evals/` holds a labelled question set whose expected
    answers are computed in pandas from the same fixtures. Accuracy is a number that
    regresses visibly when a prompt changes, and CI gates on it.

---

## Architecture

The backend is laid out as the pipeline it implements, so each stage is one folder:

```
backend/app/
├── ingestion/          files in, tables out
│   ├── engine.py               DuckDB session: CSV/Excel/JSON/Parquet loaders + execution
│   ├── schema_profiler.py      schema text for the prompt + schema-RAG narrowing
│   └── naming.py               file/sheet names -> safe SQL identifiers
├── intelligence/       question in, SQL out
│   ├── relationship_detector.py  cross-file join keys (name + dtype + value overlap)
│   ├── ambiguity_detector.py     underspecified questions: assume-and-state, or ask
│   ├── sql_generator.py          native or LangChain generation path
│   ├── prompts.py
│   └── llm/                      provider abstraction (Ollama / Groq)
├── analytics/          SQL in, rows out
│   ├── query_validator.py      SELECT-only guardrail (sqlglot)
│   └── pipeline.py             the /ask orchestration + self-correction loop
├── validation/         is this answer trustworthy?
│   ├── data_quality.py         nulls, duplicates, constants, numbers-as-text
│   ├── result_validator.py     does the result answer the question asked?
│   ├── confidence.py           a level derived from what actually happened
│   └── pii.py                  masking for prompt samples
├── visualization/
│   └── chart_builder.py        chart type from result shape
└── runtime/
    ├── session_store.py        per-session engine, history, cached profile
    └── settings.py             runtime overrides
```

A question travels down that list in order: **ingestion** has already run, **intelligence**
turns the question into SQL, **analytics** validates and executes it, **validation** decides
what caveats the answer carries, and **visualization** picks how to draw it.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 15 (App Router, TS), Tailwind, Recharts | Fast, typed, React-native charting |
| Backend | FastAPI (Python 3.12) | Async, typed request/response via Pydantic |
| Query engine | **DuckDB** (in-process) | Reads CSV/Excel natively, real SQL, zero infrastructure |
| SQL safety | `sqlglot` | Parse-level validation, not regex guessing |
| Orchestration | Explicit pipeline (LangChain LCEL optional) | Bounded and debuggable by default; framework path available via config |
| Model (local) | **Qwen2.5-Coder 3B** via Ollama | Open-source, strong at SQL, data never leaves the machine. 3B stays usable without a GPU; 7B is more accurate on unusual joins |
| Model (hosted) | **gpt-oss-120b** via Groq | Open-weights, fast, free tier. Any OpenAI-compatible model works — set `GROQ_MODEL` |

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

Step-by-step instructions, including the free-tier gotchas, are in
**[DEPLOY.md](DEPLOY.md)**. [`render.yaml`](render.yaml) is a Render Blueprint, so the
backend deploys from the dashboard without hand-entering settings.

| Piece | Where | Notes |
|---|---|---|
| Frontend | Vercel | Root Directory **must** be `frontend`; set `NEXT_PUBLIC_API_URL` to the backend URL (inlined at build time) |
| Backend | Render / Fly / any Docker host | Blueprint covers it; afterwards set `CORS_ORIGINS` to your Vercel origin |

The backend needs a **persistent process** — serverless will not do, because each session
holds a live in-process DuckDB connection with the uploaded tables.

Hosted model runtimes cannot run Ollama, which is exactly why the provider is an
abstraction — the same image runs local or hosted on a config flag.

You can also deploy with **no key at all** and let each visitor paste their own in the settings
panel (see [Credentials](#credentials)). Nothing is billed to you, and one visitor's key is
never visible to another.

---

## Tests

```bash
cd backend
.venv/Scripts/python.exe tests/test_pipeline.py       # 15
.venv/Scripts/python.exe tests/test_session_key.py    # 6
.venv/Scripts/python.exe tests/test_validation.py     # 14
```

### Eval suite

```bash
.venv/Scripts/python.exe evals/run_eval.py --mock     # no API key needed
.venv/Scripts/python.exe evals/run_eval.py            # against the configured model
```

A labelled set of 16 questions — aggregates, filters, grouping, trends, cross-file joins,
two refusals for absent data and two for unsafe requests. Expected values are computed in
pandas from the same fixtures, so the suite cannot drift into blessing a wrong answer.
**16/16 against `openai/gpt-oss-120b`.** `--mock` swaps in scripted SQL to exercise the
pipeline without a model, which is what CI runs on every push (`--min-accuracy 1.0`).

37 tests in three suites. `test_pipeline.py` (15) covers the parts that must be right
regardless of which model is plugged in; `test_session_key.py` (8) drives the real app over
HTTP to assert the bring-your-own-key security properties and table removal; `test_validation.py` (14) covers
data quality, result validation, confidence and ambiguity. Between them:
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
| `DELETE /session/{id}/table/{name}` | Remove one loaded table; returns the refreshed schema (joins and quality recomputed) |
| `PUT /session/{id}/key` | Attach a bring-your-own API key to **one session** (verified first; reports `has_key`, never the key) |
| `DELETE /session/{id}/key` | Forget that session's key and fall back to the server environment |
| `DELETE /session/{id}` | Destroy session and its data |

### Supported file types

`.csv` `.tsv` `.txt` · `.xlsx` `.xls` (each sheet becomes a table) · `.json` `.ndjson` `.jsonl`
(nested objects flattened to dotted columns) · `.parquet`

The app is schema-agnostic — it introspects whatever columns arrive, so any *tabular* data works.

### Credentials

The default is a key in the server environment. `GET /config` reports only whether a backend is
*available* (a boolean) — never the key.

The settings panel also accepts a **bring-your-own key**, so a reviewer can try a deployed
instance with their own Groq key instead of being handed one. That path is deliberately narrow:

- **Session-scoped, not global.** A single key settable over HTTP would let any visitor replace
  the key that everyone else's questions are billed to. The key attaches to one session and is
  invisible to every other session.
- **Verified before it is stored** (`GET /models` — no tokens spent), so a typo fails at the
  field rather than on the next question.
- **Memory only.** Never written to disk, never returned by any endpoint, absent from
  `repr(Session)`, and gone when the session expires or the process restarts.
- **Never persisted to `.env`.** Writing a secret to server configuration from a web request is
  the thing this design is avoiding.

`POST /ask` prefers a session key when present and otherwise falls back to the environment.
`tests/test_session_key.py` asserts these properties against the running app: no echo, no
cross-session leak, rejected keys not stored.

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
