'use client';

import { useState } from 'react';
import { Cpu, Loader2, Lock, ShieldCheck, X } from 'lucide-react';

import { updateSettings } from '@/lib/api';
import type { AppConfig, LlmBackend } from '@/lib/types';

interface Props {
  config: AppConfig;
  onConfigChange: (config: AppConfig) => void;
  onClose: () => void;
}

const BACKENDS: { value: LlmBackend; label: string; blurb: string }[] = [
  { value: 'auto', label: 'Auto', blurb: 'Prefer local, fall back to hosted' },
  { value: 'ollama', label: 'Local (Ollama)', blurb: 'Nothing leaves this machine' },
  { value: 'groq', label: 'Hosted (Groq)', blurb: 'Only schema + question transit' },
];

export default function SettingsPanel({ config, onConfigChange, onClose }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  function availability(b: LlmBackend): boolean {
    if (b === 'ollama') return config.available_backends.ollama;
    if (b === 'groq') return config.available_backends.groq;
    return config.available_backends.ollama || config.available_backends.groq;
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
                    <span>
                      <span className="block text-sm font-medium text-slate-800">{b.label}</span>
                      <span className="block text-xs text-slate-500">{b.blurb}</span>
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

          {/* ---- credentials note ---- */}
          <section className="flex items-start gap-2.5 rounded-lg bg-slate-50 px-3 py-2.5">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
            <p className="text-xs text-slate-600">
              API keys are configured on the server and are never sent to the browser or settable
              here. Your uploaded rows stay in DuckDB — only the schema reaches the model.
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
