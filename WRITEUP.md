# Approach, Key Decisions, and What's Next

## The problem behind the problem

"Ask questions about your spreadsheet in plain English" looks like an LLM problem. It isn't.
The brief asks for a **correct** answer, and the obvious implementation — put rows in a prompt
and ask the model for a total — is exactly the one that produces confident, wrong numbers.

So the first decision framed everything else: **the model must not do arithmetic.**

## Approach: text-to-SQL over DuckDB

The LLM translates English into SQL. **DuckDB** executes it and produces the numbers. The LLM
then explains the *result it was handed* — never the source data.

```
question → LLM (schema only) → SQL → guardrail → DuckDB → real numbers → chart + explanation
```

Three properties fall out of this, and each maps to something the brief asked for:

- **Correctness** — every figure is computed by a SQL engine. My test suite asserts the app's
  output equals a pandas ground truth.
- **Cross-file analysis** — multiple files become multiple tables in one database, so
  "cross-file" is just a `JOIN`. Each Excel *sheet* becomes its own table too.
- **Cost and privacy** — only the schema enters the prompt, never the rows. Token cost per
  question is ~constant whether the file has 100 rows or 100 million.

## Key decisions

**DuckDB over pandas-agent or RAG.** A pandas code-execution agent is an arbitrary-code-execution
surface. RAG is superb for prose and wrong for aggregation — you cannot retrieve your way to a
`SUM`. DuckDB gives real SQL semantics with zero infrastructure.

**RAG at the schema layer, not the data layer.** Embedding rows would be the wrong tool. But with
many or very wide tables, sending every schema each turn does get expensive — so above a threshold
the app retrieves only the tables/columns relevant to the question (always keeping detected join
keys). RAG earns its place at the metadata layer.

**A provider abstraction, because deployment forced it.** Hosted platforms can't run Ollama.
Rather than pick one, both open-source backends sit behind one interface: local Qwen2.5-Coder for
privacy, hosted Llama 3.3 for a public demo. Switching is a config flag, not a code change.

**Bounded everything.** The failure mode that produces horror-story bills is an unbounded agent
loop. There is no open-ended loop here: retries cap at 3, output tokens are capped, conversation
history is a rolling window of the last 4 turns (questions + SQL, never result rows), and a
per-session token budget hard-stops the session.

**Framework as an option, not a foundation.** I considered LangChain's SQL agent, LangGraph and CrewAI.
This workload is not agentic: it is one bounded, well-defined chain (schema → SQL → validate →
execute → chart → explain) that fits in ~150 lines of explicit Python. A framework would have
added an orchestration layer and prompt indirection over a path where I need exact control of
two things the brief cares about most — **correctness** and **cost**. LangChain's SQL agent is a
ReAct loop that can issue many model calls per question and is harder to constrain; hidden loops
are precisely what produce runaway bills. Keeping the pipeline explicit means I can read the exact
prompt when SQL generation misfires, and every guardrail is mine to enforce.

So I drew the line at the *generation step*: `SQL_GENERATOR=langchain` swaps in an LCEL chain
(`ChatPromptTemplate | ChatModel | StrOutputParser`) over a custom LangChain chat model wrapping
the same providers. A test asserts both paths return **identical SQL, rows and charts** — because
the framework owns prompt assembly only, while guardrails, execution and the retry loop stay
outside it. That is the boundary I'd defend: use a framework for ergonomics, never for the part
where correctness and spend are decided. If scope grew to multi-step planning across heterogeneous
tools, LangGraph's explicit state machine would be the right next call.

## Delta solutioning — the part that isn't just calling a model

- **Self-correcting SQL loop.** Failed SQL is fed back with its DuckDB error and retried. This is
  the single biggest robustness win; without it the app breaks on the first unusual column name.
- **Guardrails, in depth.** Queries are parsed with `sqlglot` and rejected unless a single
  read-only `SELECT`. My own test suite caught that this *wasn't enough* —
  `SELECT * FROM read_csv_auto('/etc/passwd')` is a perfectly valid SELECT. Filesystem/network
  functions are now blocked by name *and* DuckDB runs with external access disabled.
- **Auto join-key detection** by name + dtype, scored by real value overlap — this is what makes
  cross-file questions work without the user explaining how files relate.
- **Auditability.** The SQL is shown with every answer. An enterprise number you can't trace is
  worthless, and it also makes the app's reasoning falsifiable.
- **Honest failure.** If the data can't answer the question, the app says so instead of inventing
  a figure. Refusing well is a feature.
- **Type coercion at ingest.** Testing revealed dates were landing as `VARCHAR`, silently breaking
  every trend question at the binder. Date-like columns are now coerced to real timestamps.

## What I'd build next

1. **An eval suite in CI** — a labelled question set with expected answers, so SQL-generation
   accuracy becomes a tracked regression metric rather than a vibe.
2. **Streaming** the SQL and explanation for perceived latency.
3. **Redis-backed sessions + file-backed DuckDB** to lift the single-worker constraint.
4. **Semantic schema retrieval** — the current relevance matching is lexical; embeddings would
   handle synonyms ("staff" vs "employees").
5. **Row-level access control** for genuine multi-tenant use, and a saved-question dashboard.

## Honest limitations

Session state is in-process, so the backend runs single-worker (the swap point is one class).
Files are held in memory. Join detection is a heuristic surfaced as hints — the model still
decides. And SQL generation quality is ultimately bounded by the model: the guardrails and retry
loop contain that risk, but they don't eliminate it, which is exactly why the SQL is always shown.
