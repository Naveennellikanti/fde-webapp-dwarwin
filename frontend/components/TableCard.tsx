'use client';

import { useState } from 'react';
import { ChevronRight, FileSpreadsheet } from 'lucide-react';
import type { TableInfo } from '@/lib/types';
import { formatNumber } from '@/lib/format';

export default function TableCard({
  table,
  defaultOpen = false,
}: {
  table: TableInfo;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 px-3 py-2.5 text-left transition hover:bg-slate-50"
      >
        <ChevronRight
          className={`mt-0.5 h-4 w-4 shrink-0 text-slate-400 transition-transform ${
            open ? 'rotate-90' : ''
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate font-mono text-[13px] font-semibold text-slate-900">
            {table.name}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
            <FileSpreadsheet className="h-3 w-3 shrink-0" />
            <span className="truncate">{table.source_file}</span>
          </div>
        </div>
        <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-slate-600">
          {formatNumber(table.row_count)} rows
        </span>
      </button>

      {open && (
        <div className="border-t border-slate-100 px-3 py-2.5">
          <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            {table.columns.length} column{table.columns.length === 1 ? '' : 's'}
          </div>
          <ul className="flex flex-wrap gap-1">
            {table.columns.map((c) => (
              <li key={c.name} className="chip" title={`${c.name} · ${c.dtype}`}>
                <span className="text-slate-800">{c.name}</span>
                <span className="text-slate-400">{c.dtype}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
