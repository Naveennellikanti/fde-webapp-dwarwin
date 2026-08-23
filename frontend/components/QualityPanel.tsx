'use client';

import { useState } from 'react';
import { AlertTriangle, ChevronRight, Info, ShieldCheck, Sparkles } from 'lucide-react';

import type { TableQualityInfo } from '@/lib/types';

/**
 * Data quality findings from upload.
 *
 * Collapsed by default and silent when there is nothing wrong: a panel that always has
 * something to say trains the user to ignore it. Warnings are the ones that change
 * whether an answer means what it appears to mean, so only those drive the summary
 * count; the rest are available on expand.
 */
export default function QualityPanel({
  quality,
  onClean,
}: {
  quality: TableQualityInfo[];
  /** Open the cleaning flow for a table. Omitted when no session is active. */
  onClean?: (table: string) => void;
}) {
  const [open, setOpen] = useState(false);

  // Tables with a fixable problem: an empty column, duplicate rows, or numbers stored
  // as text. Only these get a Clean action — a "5% null" note is not something to
  // auto-fix.
  const fixableKinds = new Set(['numeric_stored_as_text', 'duplicate_rows', 'all_null']);
  const fixableTables = Array.from(
    new Set(
      quality
        .filter((q) => q.issues.some((i) => fixableKinds.has(i.kind)))
        .map((q) => q.table)
    )
  );

  const warnings = quality.flatMap((q) =>
    q.issues.filter((i) => i.severity === 'warning').map((i) => ({ table: q.table, ...i }))
  );
  const infos = quality.flatMap((q) =>
    q.issues.filter((i) => i.severity === 'info').map((i) => ({ table: q.table, ...i }))
  );

  if (quality.length === 0) return null;

  const clean = warnings.length === 0 && infos.length === 0;

  return (
    <section className="border-t border-slate-200 px-5 py-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-left"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 text-slate-400 transition-transform ${open ? 'rotate-90' : ''}`}
          aria-hidden
        />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Data quality
        </span>
        <span className="ml-auto inline-flex items-center gap-1">
          {clean ? (
            <span className="inline-flex items-center gap-1 rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
              <ShieldCheck className="h-2.5 w-2.5" aria-hidden />
              clean
            </span>
          ) : (
            <>
              {warnings.length > 0 && (
                <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                  {warnings.length} to check
                </span>
              )}
              {warnings.length === 0 && infos.length > 0 && (
                <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                  {infos.length} note{infos.length === 1 ? '' : 's'}
                </span>
              )}
            </>
          )}
        </span>
      </button>

      {open && (
        <div className="mt-2.5 space-y-2">
          {clean && (
            <p className="text-xs leading-relaxed text-slate-500">
              No missing values, duplicate rows or type problems worth flagging.
            </p>
          )}

          {onClean &&
            fixableTables.map((t) => (
              <button
                key={`clean-${t}`}
                type="button"
                onClick={() => onClean(t)}
                className="flex w-full items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 transition hover:bg-indigo-100"
              >
                <Sparkles className="h-3 w-3 shrink-0" aria-hidden />
                Review &amp; clean <span className="font-mono">{t}</span>
              </button>
            ))}

          {warnings.map((w, i) => (
            <p key={`w-${i}`} className="flex items-start gap-1.5 text-xs leading-relaxed text-amber-900">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-600" aria-hidden />
              <span>
                <span className="font-mono text-[10px] text-slate-500">{w.table}</span>{' '}
                {w.message}
              </span>
            </p>
          ))}

          {infos.map((n, i) => (
            <p key={`i-${i}`} className="flex items-start gap-1.5 text-xs leading-relaxed text-slate-500">
              <Info className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" aria-hidden />
              <span>
                <span className="font-mono text-[10px] text-slate-400">{n.table}</span>{' '}
                {n.message}
              </span>
            </p>
          ))}

          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 border-t border-slate-100 pt-2">
            {quality.map((q) => (
              <div key={q.table} className="col-span-2 flex items-baseline justify-between">
                <dt className="truncate font-mono text-[10px] text-slate-500">{q.table}</dt>
                <dd className="nums shrink-0 text-[10px] text-slate-400">
                  {q.row_count.toLocaleString()} rows
                  {q.duplicate_rows > 0 && ` · ${q.duplicate_rows.toLocaleString()} dupes`}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
