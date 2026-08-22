'use client';

import { useState } from 'react';
import { AlertTriangle, Info, ShieldCheck } from 'lucide-react';

import type { AskResponse, ConfidenceLevel } from '@/lib/types';

/* Confidence is shown as a word, not a percentage. The inputs are coarse — attempts,
   caveats, whether the schema was narrowed — so "medium" is honest where "0.62" would
   imply a precision the signal does not have. Clicking reveals the reasons, because a
   label the user cannot interrogate is just decoration. */
const STYLES: Record<ConfidenceLevel, { chip: string; label: string }> = {
  high: { chip: 'border-emerald-200 bg-emerald-50 text-emerald-700', label: 'High confidence' },
  medium: { chip: 'border-amber-200 bg-amber-50 text-amber-800', label: 'Medium confidence' },
  low: { chip: 'border-red-200 bg-red-50 text-red-700', label: 'Low confidence' },
};

export function ConfidenceBadge({
  level,
  reasons,
}: {
  level: ConfidenceLevel;
  reasons: string[];
}) {
  const [open, setOpen] = useState(false);
  const style = STYLES[level];

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-medium transition ${style.chip}`}
        title="How this was judged"
      >
        <ShieldCheck className="h-3 w-3 shrink-0" aria-hidden />
        {style.label}
      </button>

      {open && reasons.length > 0 && (
        <span className="absolute bottom-full left-0 z-20 mb-1.5 w-72 rounded-lg border border-slate-200 bg-white p-2.5 text-left shadow-lift">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Why
          </span>
          <ul className="space-y-0.5">
            {reasons.map((r, i) => (
              <li key={i} className="text-xs leading-relaxed text-slate-600">
                · {r}
              </li>
            ))}
          </ul>
        </span>
      )}
    </span>
  );
}

/** Caveats and stated assumptions, rendered above the numbers rather than below them. */
export function AnswerNotices({ res }: { res: AskResponse }) {
  const { caveats, assumptions } = res;
  if (caveats.length === 0 && assumptions.length === 0) return null;

  return (
    <div className="mt-3 space-y-1.5">
      {assumptions.map((a, i) => (
        <p
          key={`a-${i}`}
          className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs leading-relaxed text-slate-600"
        >
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
          <span>
            <span className="font-medium text-slate-700">Assumed:</span> {a}
          </span>
        </p>
      ))}
      {caveats.map((c, i) => (
        <p
          key={`c-${i}`}
          className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-2.5 py-1.5 text-xs leading-relaxed text-amber-900"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />
          <span>{c}</span>
        </p>
      ))}
    </div>
  );
}

/**
 * Shown when the question was genuinely unresolvable. Each option re-asks the question
 * with the measure named, so choosing costs one click rather than retyping.
 */
export function ClarificationCard({
  res,
  onChoose,
}: {
  res: AskResponse;
  onChoose: (question: string) => void;
}) {
  return (
    <div className="animate-fade-up rounded-xl border border-indigo-200 bg-indigo-50/50 p-5 shadow-card">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-indigo-100 text-indigo-700">
          <Info className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-indigo-900">One thing first</h3>
          <p className="mt-1 text-sm leading-relaxed text-indigo-900/90">{res.answer}</p>

          {res.clarification_options.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {res.clarification_options.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => onChoose(`${res.question} (by ${opt})`)}
                  className="rounded-md border border-indigo-300 bg-white px-2.5 py-1 font-mono text-xs text-indigo-700 transition hover:bg-indigo-100"
                >
                  by {opt}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
