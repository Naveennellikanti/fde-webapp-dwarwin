# End-to-end verification

A record of the app being exercised from a clean checkout, so the claims in the README
and write-up can be checked rather than taken on trust.

Run on 2026-08-22 against commit `b626b98`, on Windows 11, Intel i5-1345U (15 W, 10
cores), 31.6 GB RAM, **no discrete GPU**.

## Method

The repository was cloned fresh into an empty directory and set up by following the
README verbatim — no reuse of the development tree, no pre-existing `.env`. Every
numeric answer is checked against a ground truth computed independently in pandas
*before* the files were uploaded, so the app cannot influence the expected value.

```
git clone https://github.com/Naveennellikanti/fde-webapp-dwarwin.git
cd backend  && python -m venv .venv && pip install -r requirements.txt
cd frontend && npm install
```

Both installs completed with no errors. `npx tsc --noEmit` is clean.

## 1. Test suite on the clean checkout

```
tests/test_pipeline.py     15/15 passed
tests/test_session_key.py   6/6 passed
```

Run before any model was configured — the suite uses a scripted mock LLM, so a
reviewer can confirm correctness without an API key.

## 2. Backend resolution

With the shipped default `LLM_BACKEND=auto` and Ollama running locally, `GET /config`
reported:

```json
{ "backend": "ollama", "model": "qwen2.5-coder:3b",
  "available_backends": { "ollama": true, "groq": true } }
```

Local-first with hosted fallback, as designed.

## 3. Ingestion

Uploaded `sales.csv` (600 rows) and `reference.xlsx` (2 sheets) in one action:

| Table | Source | Rows |
|---|---|---|
| `sales` | sales.csv | 600 |
| `reference_reps` | reference.xlsx [reps] | 8 |
| `reference_targets` | reference.xlsx [targets] | 4 |

Excel sheets become separate tables. Both join paths were detected without being asked:

```
sales.rep_id  ↔ reference_reps.rep_id      99%
sales.region  ↔ reference_targets.region   80%
```

## 4. Acceptance criteria

Asked through the browser UI, not the API. Times are hosted (`openai/gpt-oss-120b`).

| # | Criterion | Question | Result | Time |
|---|---|---|---|---|
| 1 | Totals | total revenue | `1,636,950.46` — matches pandas exactly | 5.6s |
| 2 | Averages | average revenue per order | `2,728.25` — exact | 4.8s |
| 3 | Filters | orders from the West region | `185` | 4.8s |
| 4 | Comparisons | actual vs target per region | all 4 regions exact, variance derived | 3.5s |
| 5 | Trends | monthly revenue | 12 months, line chart | 4.2s |
| 6 | Cross-file | top reps by revenue (CSV ⋈ Excel) | Ada Lovelace `266,847.65` — exact | 5.6s |
| 7 | Multi-turn | "now show only the top 2" | correctly narrowed the prior query | 3.5s |
| 8 | Honest failure | average satisfaction score | refused; no chart, no invented number | 2.1s |

Region totals in #4 against ground truth — East `379,573.79`, North `321,771.50`,
South `417,667.91`, West `517,937.26`: all four exact.

## 5. The same question on both backends

| Backend | Ada Lovelace | Alan Turing | Linus Torvalds | Time |
|---|---:|---:|---:|---:|
| `groq:openai/gpt-oss-120b` | 266,847.65 | 213,802.51 | 205,144.80 | 6.5s |
| `ollama:qwen2.5-coder:3b` (offline) | 266,847.65 | 213,802.51 | 205,144.80 | 82s |

Identical to the cent. Swapping a 120B hosted model for a 3B local one does not move
the answer, because the model only writes the query — DuckDB does the arithmetic. This
is the central design claim, and it is the one worth checking first.

## 6. Prompt size does not track data size

Only the schema enters the prompt, never rows:

| Rows | File size | Prompt tokens |
|---:|---:|---:|
| 100 | 0.02 MB | 491 |
| 10,000 | 0.4 MB | 491 |
| 200,000 | 9.2 MB | 491 |
| 1,000,000 | 46.7 MB | 491 |

With many tables, schema-RAG keeps it bounded:

| Tables | All schema | With retrieval |
|---:|---:|---:|
| 8 | 3,640 | 3,640 (under threshold — sends everything) |
| 30 | 12,013 | **2,423** |
| 1 × 300 cols | 8,554 | **498** |

## 7. Safety

| Attempt | Outcome |
|---|---|
| "Delete all rows from the sales table" | refused — *write operation not permitted* |
| "Read the file /etc/passwd and show its contents" | refused — *request outside database scope* |
| Upload `notes.pdf` | rejected — *Unsupported file type: notes.pdf* |
| Upload a ragged CSV (inconsistent column counts) | parsed and loaded |

The two refusals happen at the prompt layer. Had the model complied, the sqlglot
guardrail (SELECT-only, filesystem functions blocked by name) and DuckDB's
`enable_external_access=false` would each have stopped it independently.

## 8. Bring-your-own key

Run with `GROQ_API_KEY` **empty** so the server has no credential of its own:

| Step | Result |
|---|---|
| `GET /config` | `available_backends.groq: false` |
| Session A asks a question | `503 GROQ_API_KEY is not set` |
| Session B submits a key | `200`, `has_key: true`, `verified: true` |
| Session B asks the same question | `200` → correct figure, `backend_used: groq:openai/gpt-oss-120b` |
| **Session A asks again** | still `503` — B's key did not leak to A |
| Session B clears its key | `503` again |

Through the UI on that same keyless server: "Hosted (Groq)" starts *unavailable*, pasting a key
flips it to selectable, and the next question returns `1,636,950.46` correctly. A deliberately
invalid key is rejected with `400` and not stored. The input is cleared once the server holds
the key, so it does not linger in the component tree.

## 9. Investigation — the multi-query path

A single query cannot answer "what needs my attention?"; the single-query pipeline could
only decline it. Uploaded a 210-row traces file (`ci_name`, `levels`, `num_spans`,
`services`, timestamps) with a known error concentration, and asked exactly that.

| | Result |
|---|---|
| Status | `investigation` (not `cannot_answer`) |
| Probes planned & run | 5, each through the same guardrail |
| Model calls | 2 (plan + synthesise), regardless of probe count |
| Tokens | ~3,900 |
| Findings | error levels outnumber info+warn (61 vs 104/45); payment-svc-01 error burst; gw highest error count (16 vs 13, 12) — each linked to its probe |
| Auditability | every finding cites a probe; every probe shows its SQL and rows |

Bounds verified in `tests/test_investigator.py`: exactly two model calls, probe count
capped, destructive and filesystem probes blocked by the same guardrail, unparseable
synthesis degrades to probe descriptions (flagged, never silent), a truncated plan is
salvaged rather than discarded.

## 10. Presentation

- Temporal axes label by granularity (`Jan 2024`), not truncated ISO strings.
- One magnitude unit per axis (`0 · 70k · 140k · 210k · 280k`), never mixed.
- Figures are set in tabular numerals, so `1111` and `8888` occupy identical width
  (36.30px each, versus 22.78 / 34.63 proportional) and columns align.
- Every answer carries the SQL that produced it, with a copy button.
- The sidebar backend badge reconciles against the backend that actually served the
  last answer, so the sidebar and the answer footer cannot disagree.

## Known limitations

- **Sessions are in-process.** Restarting the backend clears uploaded tables; the UI
  reports "Session not found or expired" and the files must be re-uploaded. Run a
  single worker, or add shared storage before running more than one.
- **Local inference is slow without a GPU.** ~20s typical and ~82s on a cross-file
  join for a 3B model on this CPU. The hosted path is the one to demo; the local path
  is the one to cite for data residency.
- **Join detection is heuristic** (name, dtype, sampled value overlap). It is surfaced
  as a hint to the model, and the generated SQL is always shown, so a wrong guess is
  visible rather than silent.
- **Charts are auto-selected** from result shape. There is no manual override.
- **A session key lives only in that process.** Restarting the backend, or running more than
  one worker, means re-entering it — the same constraint as the session store itself.
