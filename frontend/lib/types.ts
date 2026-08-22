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
  quality: TableQualityInfo[];
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

export type AskStatus =
  | 'ok'
  | 'cannot_answer'
  | 'empty'
  | 'error'
  | 'needs_clarification';

export type ConfidenceLevel = 'high' | 'medium' | 'low';

export type QualitySeverity = 'info' | 'warning';

export interface ColumnQualityInfo {
  name: string;
  dtype: string;
  null_count: number;
  null_pct: number;
  distinct_count: number;
}

export interface QualityIssueInfo {
  kind: string;
  severity: QualitySeverity;
  message: string;
  column: string | null;
}

export interface TableQualityInfo {
  table: string;
  row_count: number;
  duplicate_rows: number;
  columns: ColumnQualityInfo[];
  issues: QualityIssueInfo[];
}

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
  /** Things the user should know about this answer without reading the SQL. */
  caveats: string[];
  /** Interpretations the app chose on the user's behalf, stated rather than hidden. */
  assumptions: string[];
  /** Populated when status is 'needs_clarification'. */
  clarification_options: string[];
  /** Derived from how the answer was produced, not from asking the model. */
  confidence: ConfidenceLevel | null;
  confidence_score: number | null;
  confidence_reasons: string[];
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

/** Non-secret settings the UI may change. Keys go through the session endpoints. */
export interface SettingsUpdate {
  schema_only?: boolean;
  llm_backend?: LlmBackend;
  sample_rows?: number;
}

/**
 * Result of attaching a bring-your-own key to the session. The key itself is never
 * returned by the API — only whether one is currently held.
 */
export interface SessionKeyState {
  session_id: string;
  has_key: boolean;
  tokens_used: number;
  verified?: boolean;
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
