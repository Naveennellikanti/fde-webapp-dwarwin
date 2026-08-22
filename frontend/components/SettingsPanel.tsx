'use client';

import { useState } from 'react';
import { Cpu, Loader2, Lock, ShieldCheck, X } from 'lucide-react';

import { clearSessionKey, getConfig, setSessionKey, updateSettings } from '@/lib/api';
import type { AppConfig, LlmBackend } from '@/lib/types';

interface Props {
  config: AppConfig;
  onConfigChange: (config: AppConfig) => void;
  onClose: () => void;
  /** Null before the session bootstraps; the key field stays disabled until then. */
  sessionId: string | null;
  hasSessionKey: boolean;
  onSessionKeyChange: (hasKey: boolean) => void;
}

const BACKENDS: { value: LlmBackend; label: string; blurb: string }[] = [
  { value: 'auto', label: 'Auto', blurb: 'Prefer local, fall back to hosted' },
  { value: 'ollama', label: 'Local (Ollama)', blurb: 'Nothing leaves this machine' },
  { value: 'groq', label: 'Hosted (Groq)', blurb: 'Only schema + question transit' },
];

export default function SettingsPanel({
  config,
  onConfigChange,
  onClose,
  sessionId,
  hasSessionKey,
  onSessionKeyChange,
}: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [keyInput, setKeyInput] = useState('');
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [keyNote, setKeyNote] = useState<string | null>(null);
  const hasKey = hasSessionKey;

  async function saveKey() {
    if (!sessionId) {
      setKeyError('No active session yet.');
      return;
    }
    setKeyBusy(true);
    setKeyError(null);
    setKeyNote(null);
    try {
      const state = await setSessionKey(sessionId, keyInput.trim());
      onSessionKeyChange(state.has_key);
      // Drop the value from React state as soon as the server has it, so it does not
      // sit in the component tree (or a devtools snapshot) longer than necessary.
      setKeyInput('');
      setKeyNote('Key verified and active for this session.');
      onConfigChange(await getConfig());
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : 'Could not save that key.');
    } finally {
      setKeyBusy(false);
    }
  }

  async function removeKey() {
    if (!sessionId) return;
    setKeyBusy(true);
    setKeyError(null);
    setKeyNote(null);
    try {
      const state = await clearSessionKey(sessionId);
      onSessionKeyChange(state.has_key);
      setKeyInput('');
      setKeyNote('Key removed. Falling back to the server configuration.');
      onConfigChange(await getConfig());
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : 'Could not clear the key.');
    } finally {
      setKeyBusy(false);
    }
  }

  async function apply(patch: Parameters<typeof updateSettings>[0]) {
    setSaving(true);
    setError(null);
    try {
      onConfigChange(await updateSettings(patch));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update settings.');
    } finally {
      setSaving(false);
    }
  }

  /** The reason a backend cannot be used, if the server gave one. */
  function note(b: LlmBackend): string {
    if (b === 'ollama') return config.backend_notes?.ollama ?? '';
    if (b === 'groq') return hasKey ? '' : (config.backend_notes?.groq ?? '');
    return '';
  }

  function availability(b: LlmBackend): boolean {
    // `/config` is session-agnostic, so `available_backends.groq` reflects only the
    // key the server was started with. A session that has brought its own key can use
    // the hosted backend regardless — without this, pasting a valid key leaves the
    // option greyed out and unselectable.
    const groqOk = config.available_backends.groq || hasKey;
    if (b === 'ollama') return config.available_backends.ollama;
    if (b === 'groq') return groqOk;
    return config.available_backends.ollama || groqOk;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Cpu className="h-4 w-4 text-indigo-600" aria-hidden />
            Settings
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" aria-hidden />}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div className="space-y-6 px-5 py-5">
          {/* ---- model backend ---- */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Model backend
            </h3>
            <div className="mt-2.5 space-y-1.5">
              {BACKENDS.map((b) => {
                const enabled = availability(b.value);
                const active = config.llm_backend === b.value;
                return (
                  <button
                    key={b.value}
                    disabled={!enabled || saving}
                    onClick={() => apply({ llm_backend: b.value })}
                    className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition
                      ${active
                        ? 'border-indigo-300 bg-indigo-50'
                        : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'}
                      ${!enabled ? 'cursor-not-allowed opacity-45' : ''}`}
                  >
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-slate-800">{b.label}</span>
                      <span className="block text-xs text-slate-500">
                        {!enabled && note(b.value) ? note(b.value) : b.blurb}
                      </span>
                    </span>
                    {!enabled ? (
                      <span className="text-[11px] text-slate-400">unavailable</span>
                    ) : active ? (
                      <span className="text-[11px] font-medium text-indigo-600">active</span>
                    ) : null}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Resolved: <span className="font-medium text-slate-700">{config.model ?? config.backend}</span>
            </p>
          </section>

          {/* ---- privacy ---- */}
          <section>
            <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              Privacy
            </h3>
            <label className="mt-2.5 flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 px-3 py-2.5 transition hover:bg-slate-50">
              <input
                type="checkbox"
                checked={config.schema_only}
                disabled={saving}
                onChange={(e) => apply({ schema_only: e.target.checked })}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span>
                <span className="block text-sm font-medium text-slate-800">Schema-only mode</span>
                <span className="block text-xs text-slate-500">
                  Send column names and types only — no data values at all. Slightly reduces SQL
                  accuracy on ambiguous columns.
                </span>
              </span>
            </label>
            <p className="mt-2 text-xs text-slate-500">
              {config.schema_only
                ? 'No data values are sent to the model.'
                : `Sending ${config.sample_rows} PII-masked sample row${config.sample_rows === 1 ? '' : 's'} per table for accuracy.`}
            </p>
          </section>

          {/* ---- bring-your-own key ---- */}
          <section>
            <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <Lock className="h-3.5 w-3.5" aria-hidden />
              Your Groq API key
              {hasKey && (
                <span className="ml-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium normal-case tracking-normal text-emerald-700">
                  in use for this session
                </span>
              )}
            </h3>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                void saveKey();
              }}
              className="mt-2.5 flex gap-2"
            >
              <input
                type="password"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder={hasKey ? '•••••••• (stored for this session)' : 'gsk_…'}
                autoComplete="off"
                spellCheck={false}
                disabled={keyBusy}
                aria-label="Groq API key"
                className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs text-slate-800 placeholder:font-sans placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-100"
              />
              <button
                type="submit"
                disabled={keyBusy || keyInput.trim().length === 0}
                className="shrink-0 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
              >
                {keyBusy ? 'Checking…' : 'Save'}
              </button>
              {hasKey && (
                <button
                  type="button"
                  disabled={keyBusy}
                  onClick={() => void removeKey()}
                  className="shrink-0 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                >
                  Clear
                </button>
              )}
            </form>

            {keyError && <p className="mt-2 text-xs text-red-700">{keyError}</p>}
            {keyNote && !keyError && <p className="mt-2 text-xs text-emerald-700">{keyNote}</p>}

            <p className="mt-2 text-xs text-slate-500">
              Verified before it is stored, then kept in memory for{' '}
              <span className="font-medium text-slate-700">this session only</span> — never
              written to disk, never sent back to the browser, and discarded when the session
              ends. Leave it empty to use the key the server was started with.
            </p>
          </section>

          {/* ---- data handling note ---- */}
          <section className="flex items-start gap-2.5 rounded-lg bg-slate-50 px-3 py-2.5">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
            <p className="text-xs text-slate-600">
              Your uploaded rows stay in DuckDB on the server — only the schema reaches the
              model. Choose the local backend and nothing leaves the machine at all.
            </p>
          </section>

          {error && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>
          )}
        </div>
      </div>
    </div>
  );
}
