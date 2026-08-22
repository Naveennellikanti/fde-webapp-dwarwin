// Mirrors backend/app/schemas.py exactly.

export type Row = Record<string, unknown>;

export interface ColumnInfo {
  name: string;
  dtype: string;
}

export interface TableInfo {
  name: string;
  source_file: string;
  columns: ColumnInfo[];
  row_count: number;
  sample_rows: Row[];
}

export interface JoinHint {
  left_table: string;
  left_column: string;
  right_table: string;
  right_column: string;
  confidence: number;
}

export interface SchemaResponse {
  session_id: string;
  tables: TableInfo[];
  joins: JoinHint[];
}

export type UploadResponse = SchemaResponse;

export interface SessionResponse {
  session_id: string;
}

export type ChartType = 'bar' | 'line' | 'scatter' | 'kpi' | 'table' | 'none';

export interface ChartSpec {
  type: ChartType;
  x: string | null;
  y: string | null;
  series: string | null;
  title: string | null;
}

export interface SqlAttempt {
  sql: string;
  error: string | null;
}

export type AskStatus = 'ok' | 'cannot_answer' | 'empty' | 'error';

export interface AskResponse {
  session_id: string;
  question: string;
  status: AskStatus;
  answer: string;
  sql: string | null;
  columns: string[];
  rows: Row[];
  chart: ChartSpec;
  attempts: SqlAttempt[];
  backend_used: string | null;
  tokens_used: number;
  truncated: boolean;
}

export type LlmBackend = 'auto' | 'ollama' | 'groq';

export interface AppConfig {
  backend: string;
  /** Concrete model id in use, e.g. "openai/gpt-oss-120b". */
  model: string | null;
  /** Configured preference, as opposed to `backend` which is what actually resolved. */
  llm_backend: LlmBackend;
  schema_only: boolean;
  sample_rows: number;
  max_upload_mb: number;
  allowed_extensions: string[];
  /** Which backends could be selected. Booleans only — the API key is never exposed. */
  available_backends: { ollama: boolean; groq: boolean };
}

/** Non-secret settings the UI may change. API keys are deliberately not settable. */
export interface SettingsUpdate {
  schema_only?: boolean;
  llm_backend?: LlmBackend;
  sample_rows?: number;
}

/** One entry in the conversation thread. */
export interface Turn {
  id: string;
  question: string;
  /** null while the request is in flight. */
  response: AskResponse | null;
  /** Transport/HTTP-level failure (as opposed to a status:"error" response). */
  transportError: string | null;
}
