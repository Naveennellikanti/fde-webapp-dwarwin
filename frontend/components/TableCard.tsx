'use client';

import { useState } from 'react';
import { ChevronRight, FileSpreadsheet, Trash2, X } from 'lucide-react';
import type { TableInfo } from '@/lib/types';
import { formatNumber } from '@/lib/format';

export default function TableCard({
  table,
  defaultOpen = false,
  onRemove,
  removing = false,
}: {
  table: TableInfo;
  defaultOpen?: boolean;
  /** Omitted when removal is not possible (e.g. no active session). */
  onRemove?: (table: string) => void;
  removing?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // Two-step rather than a modal: re-uploading is easy, but silently losing a large
  // file to a stray click is not, and a dialog for this is heavier than it deserves.
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="card overflow-hidden">
      {/* A row, not one big button: the toggle and the remove control are separate
          actions, and nesting interactive elements is invalid. */}
      <div className="flex items-start gap-1 px-1 py-1">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-start gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-slate-50"
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
        </button>

        <div className="flex shrink-0 items-center gap-1 pt-1.5">
          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-slate-600">
            {formatNumber(table.row_count)} rows
          </span>

          {onRemove &&
            (confirming ? (
              <span className="flex items-center gap-0.5">
                <button
                  type="button"
                  disabled={removing}
                  onClick={() => {
                    setConfirming(false);
                    onRemove(table.name);
                  }}
                  className="rounded px-1.5 py-0.5 text-[11px] font-medium text-red-700 transition hover:bg-red-50 disabled:opacity-50"
                >
                  {removing ? '…' : 'Remove'}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  aria-label="Keep this table"
                  className="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                >
                  <X className="h-3 w-3" aria-hidden />
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                aria-label={`Remove ${table.name}`}
                title="Remove this table from the session"
                className="rounded p-1 text-slate-300 transition hover:bg-red-50 hover:text-red-600"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </button>
            ))}
        </div>
      </div>

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
