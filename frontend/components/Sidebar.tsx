'use client';

import { Cpu, Database, Link2, Settings, ShieldCheck } from 'lucide-react';
import type { AppConfig, JoinHint, TableInfo, TableQualityInfo } from '@/lib/types';
import UploadZone from './UploadZone';
import TableCard from './TableCard';
import QualityPanel from './QualityPanel';

const PRIVACY_NOTE =
  'Your data stays in DuckDB — only the schema is sent to the model.';

interface Props {
  config: AppConfig | null;
  tables: TableInfo[];
  joins: JoinHint[];
  quality: TableQualityInfo[];
  onFiles: (files: File[]) => void;
  uploading: boolean;
  uploadDisabled: boolean;
  uploadError: string | null;
  onOpenSettings: () => void;
  onRemoveTable: (table: string) => void;
  /** Name of the table currently being removed, if any. */
  removingTable: string | null;
  onClean?: (table: string) => void;
}

export default function Sidebar({
  config,
  tables,
  joins,
  quality,
  onFiles,
  uploading,
  uploadDisabled,
  uploadError,
  onOpenSettings,
  onRemoveTable,
  removingTable,
  onClean,
}: Props) {
  const maxTables = config?.limits?.max_tables_per_session ?? null;
  const atTableCap = maxTables != null && tables.length >= maxTables;
  return (
    <aside className="flex h-screen w-[320px] shrink-0 flex-col border-r border-slate-200 bg-white">
      {/* Header */}
      <div className="border-b border-slate-200 px-5 pb-4 pt-5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 text-white">
            <Database className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-[15px] font-semibold leading-tight text-slate-900">
              Data Q&amp;A
            </h1>
            <p className="text-[11px] leading-tight text-slate-500">
              Ask your spreadsheets in plain English
            </p>
          </div>
          <button
            type="button"
            onClick={onOpenSettings}
            aria-label="Open settings"
            title="Model backend and privacy settings"
            className="shrink-0 rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span
            className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-accent-200 bg-accent-50 px-2 py-1 text-[11px] font-medium text-accent-700"
            title="Active model backend"
          >
            <Cpu className="h-3 w-3 shrink-0" />
            <span className="truncate font-mono">
              {config ? config.backend : 'connecting…'}
            </span>
          </span>

          <span
            className="inline-flex cursor-help items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700"
            title={PRIVACY_NOTE}
            aria-label={PRIVACY_NOTE}
          >
            <ShieldCheck className="h-3 w-3 shrink-0" />
            {config?.schema_only ? 'Schema only' : 'Private'}
          </span>
        </div>
      </div>

      {/* Scrollable body */}
      <div className="scroll-thin flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <section>
          <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Data sources
          </h2>
          <UploadZone
            onFiles={onFiles}
            uploading={uploading}
            disabled={uploadDisabled || atTableCap}
            error={uploadError}
            maxUploadMb={config?.max_upload_mb ?? null}
          />
          {maxTables != null && (
            <p className={`mt-1.5 text-[11px] ${atTableCap ? 'text-amber-600' : 'text-slate-400'}`}>
              {atTableCap
                ? `Table limit reached (${tables.length}/${maxTables}). Remove one to add more.`
                : `${tables.length} of ${maxTables} tables used`}
            </p>
          )}
        </section>

        {tables.length > 0 && (
          <section>
            <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Tables ({tables.length})
            </h2>
            <div className="space-y-2">
              {tables.map((t, i) => (
                <TableCard
                  key={t.name}
                  table={t}
                  defaultOpen={tables.length === 1 && i === 0}
                  onRemove={onRemoveTable}
                  removing={removingTable === t.name}
                />
              ))}
            </div>
          </section>
        )}

        {joins.length > 0 && (
          <section>
            <h2 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              <Link2 className="h-3 w-3" />
              Detected relationships
            </h2>
            <ul className="space-y-1.5">
              {joins.map((j, i) => (
                <li
                  key={`${j.left_table}.${j.left_column}-${j.right_table}.${j.right_column}-${i}`}
                  className="card flex items-center justify-between gap-2 px-2.5 py-2"
                >
                  <span className="min-w-0 break-all font-mono text-[11px] text-slate-700">
                    {j.left_table}.{j.left_column}
                    <span className="mx-1 text-accent-600" aria-hidden>
                      ↔
                    </span>
                    {j.right_table}.{j.right_column}
                  </span>
                  <span
                    className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-slate-600"
                    title="Join confidence"
                  >
                    {Math.round(j.confidence * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {/* Quality findings sit above the privacy note: both are things to know about the
          data before trusting an answer, and neither belongs in the scrolling list. */}
      <QualityPanel quality={quality} onClean={onClean} />

      {/* Footer */}
      <div className="border-t border-slate-200 px-5 py-3">
        <p className="flex items-start gap-1.5 text-[11px] leading-snug text-slate-500">
          <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-emerald-600" />
          <span>{PRIVACY_NOTE}</span>
        </p>
      </div>
    </aside>
  );
}
