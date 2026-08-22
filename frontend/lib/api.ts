import type {
  AppConfig,
  AskResponse,
  SchemaResponse,
  SessionKeyState,
  SessionResponse,
  SettingsUpdate,
  UploadResponse,
} from './types';

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, '') || 'http://localhost:8000';

/** Error carrying the FastAPI `detail` string (or a readable fallback). */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail = `Request failed (${res.status} ${res.statusText || 'error'}).`;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === 'object' && 'detail' in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === 'string' && d.trim()) {
        detail = d;
      } else if (Array.isArray(d)) {
        // FastAPI validation errors come back as a list of objects.
        const parts = d
          .map((item) =>
            item && typeof item === 'object' && 'msg' in item
              ? String((item as { msg: unknown }).msg)
              : JSON.stringify(item)
          )
          .filter(Boolean);
        if (parts.length) detail = parts.join('; ');
      }
    }
  } catch {
    /* body was not JSON — keep the status-based fallback */
  }
  return new ApiError(detail, res.status);
}

function networkError(e: unknown): ApiError {
  const hint = `Could not reach the API at ${API_URL}. Is the backend running?`;
  if (e instanceof ApiError) return e;
  return new ApiError(hint, 0);
}

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: 'no-store' });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

export function createSession(): Promise<SessionResponse> {
  return postJson<SessionResponse>('/session', {});
}

export function getConfig(): Promise<AppConfig> {
  return getJson<AppConfig>('/config');
}

/** Update non-secret runtime settings. Returns the refreshed config. */
export async function updateSettings(patch: SettingsUpdate): Promise<AppConfig> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as AppConfig;
}

/**
 * Attach a bring-your-own API key to this session (empty string clears it).
 *
 * The key is sent once and never read back: the response reports only `has_key`. It is
 * held in the backend's memory for this session alone, so it cannot affect anyone
 * else's questions and is gone when the session expires.
 */
export async function setSessionKey(
  sessionId: string,
  apiKey: string
): Promise<SessionKeyState> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/session/${sessionId}/key`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as SessionKeyState;
}

export async function clearSessionKey(sessionId: string): Promise<SessionKeyState> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/session/${sessionId}/key`, { method: 'DELETE' });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as SessionKeyState;
}

export function getSchema(sessionId: string): Promise<SchemaResponse> {
  return getJson<SchemaResponse>(`/schema/${encodeURIComponent(sessionId)}`);
}

export function ask(sessionId: string, question: string): Promise<AskResponse> {
  return postJson<AskResponse>('/ask', { session_id: sessionId, question });
}

/**
 * Multipart upload. `session_id` is a plain form field; every file is appended
 * under the repeated field name "files", matching `files: list[UploadFile]`.
 */
export async function uploadFiles(
  sessionId: string,
  files: File[]
): Promise<UploadResponse> {
  const form = new FormData();
  form.append('session_id', sessionId);
  for (const f of files) form.append('files', f, f.name);

  let res: Response;
  try {
    // No Content-Type header: the browser sets the multipart boundary itself.
    res = await fetch(`${API_URL}/upload`, { method: 'POST', body: form });
  } catch (e) {
    throw networkError(e);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as UploadResponse;
}
