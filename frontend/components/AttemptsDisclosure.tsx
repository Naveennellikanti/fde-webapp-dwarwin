'use client';

import { useState } from 'react';
import { ChevronRight, RefreshCw } from 'lucide-react';
import type { SqlAttempt } from '@/lib/types';

/** Surfaces the self-correction loop: every SQL attempt and the error that killed it. */
export default function AttemptsDisclosure({ attempts }: { attempts: SqlAttempt[] }) {
  const [open, setOpen] = useState(false);
  if (attempts.length <= 1) return null;

  return (
    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-medium text-amber-800 transition hover:bg-amber-100/70"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-amber-500 transition-transform ${
            open ? 'rotate-90' : ''
          }`}
        />
        <RefreshCw className="h-3.5 w-3.5 shrink-0 text-amber-500" />
        Self-corrected ({attempts.length} attempts)
      </button>

      {open && (
        <ol className="space-y-2 border-t border-amber-200 p-2.5">
          {attempts.map((a, i) => {
            const failed = Boolean(a.error);
            return (
              <li key={i}>
                <div className="mb-1 flex items-center gap-2 text-[11px] font-medium">
                  <span className="rounded bg-amber-200/70 px-1.5 py-0.5 text-amber-900">
                    Attempt {i + 1}
                  </span>
                  <span className={failed ? 'text-red-700' : 'text-emerald-700'}>
                    {failed ? 'failed' : 'succeeded'}
                  </span>
                </div>
                <pre className="code-block">{a.sql}</pre>
                {a.error && (
                  <p className="mt-1 break-words rounded border border-red-200 bg-red-50 px-2 py-1 font-mono text-[11px] leading-4 text-red-800">
                    {a.error}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
