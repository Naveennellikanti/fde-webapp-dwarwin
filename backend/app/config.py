"""Central configuration, loaded from environment variables.

Everything that changes between local (Ollama) and hosted (Groq) lives here so the
rest of the codebase never branches on deployment target.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- LLM backend selection -------------------------------------------------
    # "auto"  -> use Ollama if reachable, otherwise fall back to Groq
    # "ollama"-> force local Ollama
    # "groq"  -> force hosted Groq
    llm_backend: Literal["auto", "ollama", "groq"] = "auto"

    # Ollama (local, data never leaves the machine).
    # 3b is the default because SQL generation is a narrow task and it stays usable on
    # a CPU-only machine (~20s/question on a 15W laptop CPU, verified). Use 7b when a
    # GPU is available or when questions involve unusual joins.
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:3b"

    # Groq (hosted, OpenAI-compatible). Requires GROQ_API_KEY.
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Open-weights model served by Groq. Verified to emit clean DuckDB SQL.
    groq_model: str = "openai/gpt-oss-120b"

    # ---- SQL generation strategy ----------------------------------------------
    # "native"    -> direct provider call (default; fewest moving parts)
    # "langchain" -> the same step as an LCEL chain over the same providers
    # Guardrails, execution and retries are identical either way.
    sql_generator: Literal["native", "langchain"] = "native"

    # ---- Generation limits (cost control) -------------------------------------
    sql_max_tokens: int = 512
    summary_max_tokens: int = 400
    temperature: float = 0.0  # deterministic SQL
    request_timeout_s: float = 60.0

    # ---- Pipeline / correctness -----------------------------------------------
    max_sql_retries: int = 3            # self-correction loop
    result_row_cap: int = 5000          # rows returned to the client
    sql_statement_timeout_s: int = 30   # DuckDB statement timeout

    # ---- Privacy (the "Claude way": useful by default, private by control) -----
    # Number of masked sample rows per table included in the schema prompt.
    # Set schema_only=True to send NO data values at all (columns + dtypes only).
    sample_rows: int = 3
    schema_only: bool = False

    # ---- Multi-turn (bounded so token cost never grows unbounded) --------------
    max_history_turns: int = 4          # rolling window of prior Q&A kept in context

    # ---- Schema-RAG (only kicks in when the schema is large) -------------------
    schema_rag_table_threshold: int = 8     # retrieve relevant tables above this many
    schema_rag_column_threshold: int = 40   # retrieve relevant columns above this many/table

    # ---- Cost guard ------------------------------------------------------------
    session_token_budget: int = 2_000_000   # hard stop per session

    # ---- Uploads ---------------------------------------------------------------
    max_upload_mb: int = 50
    session_ttl_minutes: int = 120

    # ---- CORS ------------------------------------------------------------------
    # Comma-separated list of allowed origins for the browser frontend.
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
