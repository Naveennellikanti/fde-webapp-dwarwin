'use client';

import { useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronRight, Info, Search } from 'lucide-react';

import type { AskResponse, FindingInfo, ProbeInfo } from '@/lib/types';
import { AnswerNotices, ConfidenceBadge } from './AnswerMeta';
import DataTable from './DataTable';
import { formatNumber } from '@/lib/format';

/**
 * The investigation view: findings first, then the probes that produced them.
 *
 * The whole point of this mode over a single query is that it *reasons across several
 * queries*, so the answer would be worthless if you had to take it on faith. Every
 * finding links to the probe it came from, and every probe shows its SQL and rows — the
 * reasoning is auditable end to end, which is the difference between this and a black box
 * that says "payment-svc looks bad".
 */
const SEVERITY: Record<FindingInfo['severity'], { icon: typeof Info; chip: string; ring: string }> = {
  watch: { icon: AlertTriangle, chip: 'text-amber-700', ring: 'bg-amber-50 text-amber-600' },
  notable: { icon: Info, chip: 'text-slate-700', ring: 'bg-indigo-50 text-indigo-600' },
  ok: { icon: CheckCircle2, chip: 'text-emerald-700', ring: 'bg-emerald-50 text-emerald-600' },
};

export default function InvestigationCard({ res }: { res: AskResponse }) {
  return (
    <article className="card animate-fade-up p-5">
      <header className="flex items-center gap-2.5">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-indigo-50 text-indigo-600">
          <Search className="h-3.5 w-3.5" aria-hidden />
        </span>
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Investigation</h3>
          <p className="text-[11px] text-slate-500">
            {res.probes.filter((p) => !p.error).length} queries run and read together
          </p>
        </div>
      </header>

      <AnswerNotices res={res} />

      <ul className="mt-4 space-y-2.5">
        {res.findings.map((f, i) => {
          const s = SEVERITY[f.severity] ?? SEVERITY.notable;
          const Icon = s.icon;
          return (
            <li key={i} className="flex items-start gap-2.5">
              <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded ${s.ring}`}>
                <Icon className="h-3 w-3" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className={`text-sm font-medium leading-snug ${s.chip}`}>{f.headline}</p>
                {f.detail && <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{f.detail}</p>}
                {f.evidence !== null && (
                  <span className="mt-0.5 inline-block text-[10px] font-medium uppercase tracking-wide text-slate-400">
                    from probe {f.evidence + 1}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <ProbeList probes={res.probes} />

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-slate-200/70 pt-2">
        {res.confidence && (
          <ConfidenceBadge level={res.confidence} reasons={res.confidence_reasons} />
        )}
        <p className="font-mono text-[11px] text-slate-400">
          {[res.backend_used, `${formatNumber(res.tokens_used)} tokens`].filter(Boolean).join(' · ')}
        </p>
      </div>
    </article>
  );
}

function ProbeList({ probes }: { probes: ProbeInfo[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-xs font-medium text-slate-500 transition hover:text-slate-700"
      >
        <ChevronRight className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden />
        {open ? 'Hide' : 'Show'} the {probes.length} probe {probes.length === 1 ? 'query' : 'queries'}
        <span className="font-normal text-slate-400">· auditable</span>
      </button>

      {open && (
        <ol className="mt-2.5 space-y-3">
          {probes.map((p, i) => (
            <li key={i} className="rounded-lg border border-slate-200 p-2.5">
              <div className="flex items-baseline gap-2">
                <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
                  {i + 1}
                </span>
                <span className="text-xs font-medium text-slate-700">{p.goal}</span>
              </div>
              <pre className="scroll-thin mt-1.5 overflow-x-auto rounded bg-slate-900 p-2 font-mono text-[11px] leading-relaxed text-slate-100">
                {p.sql}
              </pre>
              {p.error ? (
                <p className="mt-1.5 text-[11px] text-red-600">Did not run: {p.error}</p>
              ) : (
                <div className="mt-1.5">
                  <DataTable columns={p.columns} rows={p.rows} truncated={false} />
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
