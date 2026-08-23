'use client';

import { useEffect, useState } from 'react';
import { Check, Loader2, Sparkles, Undo2, X } from 'lucide-react';

import { applyCleaning, getCleaningProposal, undoCleaning } from '@/lib/api';
import type { CleaningOp, CleaningProposal, UploadResponse } from '@/lib/types';

/**
 * Propose → approve → apply cleaning for one table.
 *
 * Nothing changes until the user ticks fixes and clicks apply, and the original is
 * snapshotted server-side so it can be undone. The fixes are deterministic (derived
 * from the quality profile, not generated), so this panel shows exactly what will
 * happen — each op carries a measured impact — rather than a model's promise.
 */
export default function CleaningPanel({
  sessionId,
  table,
  onApplied,
  onClose,
}: {
  sessionId: string;
  table: string;
  /** Receives the refreshed schema after apply/undo so the sidebar updates. */
  onApplied: (res: UploadResponse) => void;
  onClose: () => void;
}) {
  const [proposal, setProposal] = useState<CleaningProposal | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getCleaningProposal(sessionId, table)
      .then((p) => {
        if (!live) return;
        setProposal(p);
        setSelected(new Set(p.ops.map((o) => o.id))); // default: everything checked
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : 'Could not load fixes.'));
    return () => {
      live = false;
    };
  }, [sessionId, table]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function run(action: 'apply' | 'undo') {
    setBusy(true);
    setError(null);
    try {
      const res =
        action === 'apply'
          ? await applyCleaning(sessionId, table, [...selected])
          : await undoCleaning(sessionId, table);
      onApplied(res);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Operation failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Sparkles className="h-4 w-4 text-indigo-600" aria-hidden />
            Clean <span className="font-mono text-slate-500">{table}</span>
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div className="max-h-[60vh] space-y-2.5 overflow-y-auto px-5 py-4">
          {!proposal && !error && (
            <p className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Finding fixes…
            </p>
          )}

          {proposal && proposal.ops.length === 0 && (
            <p className="text-sm text-slate-600">
              Nothing to clean — no missing columns, duplicate rows or mistyped values found.
            </p>
          )}

          {proposal?.ops.map((op: CleaningOp) => (
            <label
              key={op.id}
              className="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 px-3 py-2.5 transition hover:bg-slate-50"
            >
              <input
                type="checkbox"
                checked={selected.has(op.id)}
                onChange={() => toggle(op.id)}
                disabled={busy}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="min-w-0">
                <span className="block text-sm text-slate-800">{op.description}</span>
                {op.impact && (
                  <span className="mt-0.5 block text-xs text-slate-500">{op.impact}</span>
                )}
              </span>
            </label>
          ))}

          {error && <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-slate-200 px-5 py-3">
          <p className="text-[11px] text-slate-500">
            Your original stays intact — this can be undone.
          </p>
          <div className="flex items-center gap-2">
            {proposal?.undo_available && (
              <button
                type="button"
                onClick={() => void run('undo')}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50 disabled:opacity-50"
              >
                <Undo2 className="h-3.5 w-3.5" aria-hidden /> Undo last clean
              </button>
            )}
            <button
              type="button"
              onClick={() => void run('apply')}
              disabled={busy || !proposal || selected.size === 0}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <Check className="h-3.5 w-3.5" aria-hidden />
              )}
              Apply {selected.size > 0 ? selected.size : ''} fix{selected.size === 1 ? '' : 'es'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
