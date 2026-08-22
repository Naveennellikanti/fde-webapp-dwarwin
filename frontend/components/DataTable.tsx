'use client';

import type { Row } from '@/lib/types';
import { formatCell, formatNumber, isNumeric } from '@/lib/format';

const MAX_ROWS = 100;

export default function DataTable({
  columns,
  rows,
  truncated,
}: {
  columns: string[];
  rows: Row[];
  truncated: boolean;
}) {
  if (!columns.length || !rows.length) return null;

  const shown = rows.slice(0, MAX_ROWS);
  const hiddenHere = rows.length - shown.length;

  return (
    <div className="mt-4">
      <div className="scroll-thin max-h-[380px] overflow-auto rounded-lg border border-slate-200">
        <table className="w-full border-collapse text-left text-[13px]">
          <thead className="sticky top-0 z-10">
            <tr>
              {columns.map((c) => (
                <th
                  key={c}
                  scope="col"
                  className="whitespace-nowrap border-b border-slate-200 bg-slate-50 px-3 py-2 font-mono text-[11px] font-semibold uppercase tracking-wide text-slate-500"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} className="even:bg-slate-50/60">
                {columns.map((c) => {
                  const v = r[c];
                  return (
                    <td
                      key={c}
                      className={`whitespace-nowrap border-b border-slate-100 px-3 py-1.5 text-slate-700 ${
                        isNumeric(v) ? 'text-right tabular-nums' : ''
                      }`}
                      title={v === null || v === undefined ? '' : String(v)}
                    >
                      {formatCell(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-1.5 text-[11px] text-slate-500">
        {truncated
          ? `Showing first ${formatNumber(shown.length)} rows — the result set was truncated by the server.`
          : hiddenHere > 0
            ? `Showing first ${formatNumber(shown.length)} of ${formatNumber(rows.length)} rows.`
            : `${formatNumber(rows.length)} row${rows.length === 1 ? '' : 's'} · ${columns.length} column${
                columns.length === 1 ? '' : 's'
              }`}
      </p>
    </div>
  );
}
