'use client';

import { useMemo } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import type { ChartSpec, Row } from '@/lib/types';
import {
  formatNumber,
  makeAxisFormatter,
  makeDateAxisFormatter,
  toNumber,
  truncateLabel,
} from '@/lib/format';

/**
 * Categorical series slots — fixed order, never cycled (mirrors the CSS
 * custom properties in globals.css). Validated against the light chart
 * surface for the lightness band, chroma floor, adjacent-pair CVD
 * separation and the normal-vision floor.
 */
const SERIES_COLORS = [
  '#4f46e5',
  '#eb6834',
  '#1baf7a',
  '#eda100',
  '#e87ba4',
  '#008300',
  '#4a3aa7',
  '#e34948',
] as const;

const GRID = '#e2e8f0';
const AXIS_INK = '#475569';
/* SVG <text> does not inherit the page font stack, so the tick names it explicitly.
   Tabular figures are applied in globals.css instead: `font-variant-numeric` is a CSS
   property rather than an SVG presentation attribute, so React drops it here. */
const TICK = {
  fill: AXIS_INK,
  fontSize: 11,
  fontFamily: 'var(--font-sans)',
} as const;
const CHART_HEIGHT = 300;

/** A 9th series is never a generated hue — it folds into "Other". */
const MAX_SERIES = SERIES_COLORS.length;
const OTHER = 'Other';

function colorAt(i: number): string {
  return SERIES_COLORS[i % SERIES_COLORS.length];
}

interface PivotResult {
  data: Row[];
  keys: string[];
}

/** Long rows -> wide rows: each unique `series` value becomes its own column. */
function pivotRows(rows: Row[], x: string, y: string, series: string): PivotResult {
  const order: string[] = [];
  const seen = new Set<string>();
  for (const r of rows) {
    const k = String(r[series] ?? '—');
    if (!seen.has(k)) {
      seen.add(k);
      order.push(k);
    }
  }

  // Cap the series count; everything past the cap folds into a single "Other".
  const kept = new Set(order.slice(0, MAX_SERIES));
  const keys = order.length > MAX_SERIES ? [...kept, OTHER] : [...kept];
  const keyFor = (k: string) => (kept.has(k) ? k : OTHER);

  const byX = new Map<string, Row>();
  const xOrder: string[] = [];
  for (const r of rows) {
    const xv = r[x];
    const xk = String(xv ?? '—');
    if (!byX.has(xk)) {
      byX.set(xk, { [x]: xv });
      xOrder.push(xk);
    }
    const bucket = byX.get(xk) as Row;
    const k = keyFor(String(r[series] ?? '—'));
    const n = toNumber(r[y]);
    if (n !== null) bucket[k] = ((bucket[k] as number | undefined) ?? 0) + n;
  }

  return { data: xOrder.map((k) => byX.get(k) as Row), keys };
}

/** Coerce the y column to real numbers so Recharts scales correctly. */
function numericRows(rows: Row[], x: string, y: string): Row[] {
  return rows.map((r) => ({ ...r, [y]: toNumber(r[y]) }));
}

function ChartTooltip({
  active,
  payload,
  label,
  labelFormat,
}: {
  active?: boolean;
  payload?: Array<{ name?: string | number; value?: unknown; color?: string }>;
  label?: unknown;
  /** Recharts does not apply `labelFormatter` when `content` is a custom component,
      so the axis formatter has to be threaded in explicitly. */
  labelFormat?: (v: unknown) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lift">
      {label !== undefined && label !== null && (
        <div className="mb-1 text-xs font-medium text-slate-900">
          {labelFormat ? labelFormat(label) : String(label)}
        </div>
      )}
      <ul className="space-y-0.5">
        {payload.map((p, i) => {
          const n = toNumber(p.value);
          return (
            <li key={i} className="flex items-center gap-2 text-xs">
              <span
                className="h-2 w-2 shrink-0 rounded-full ring-2 ring-white"
                style={{ backgroundColor: p.color ?? colorAt(0) }}
                aria-hidden
              />
              <span className="text-slate-600">{String(p.name ?? '')}</span>
              <span className="ml-auto font-medium tabular-nums text-slate-900">
                {n === null ? String(p.value ?? '—') : formatNumber(n)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const legendStyle = { fontSize: 11, color: AXIS_INK, paddingTop: 8 } as const;

export default function ChartView({
  chart,
  rows,
}: {
  chart: ChartSpec;
  rows: Row[];
}) {
  const { type, x, y, series, title } = chart;

  const pivoted = useMemo<PivotResult | null>(() => {
    if (!series || !x || !y) return null;
    if (type !== 'bar' && type !== 'line') return null;
    return pivotRows(rows, x, y, series);
  }, [rows, x, y, series, type]);

  const plain = useMemo<Row[]>(() => {
    if (!x || !y) return [];
    return numericRows(rows, x, y);
  }, [rows, x, y]);

  if (type === 'kpi') return <KpiCard chart={chart} rows={rows} />;
  if (type === 'table' || type === 'none') return null;
  if (!rows.length) return null;

  // A chart needs both axes resolved; otherwise fall through to the table.
  if (!x || !y) return null;

  const multi = pivoted !== null && pivoted.keys.length > 1;
  const data = pivoted ? pivoted.data : plain;
  const seriesKeys = pivoted ? pivoted.keys : [y];

  // One unit per axis, derived from that axis's own values.
  const yValues: number[] = [];
  for (const r of data) {
    for (const k of seriesKeys) {
      const n = toNumber(r[k]);
      if (n !== null) yValues.push(n);
    }
  }
  const formatY = makeAxisFormatter(yValues);
  const formatX = makeAxisFormatter(
    plain.map((r) => toNumber(r[x])).filter((n): n is number => n !== null)
  );
  /* A category axis is often temporal (`date_trunc('month', …)` returns timestamps).
     When every x value parses as a date, label the axis by date granularity instead of
     truncating the ISO string — otherwise all ticks read "2024-01-01T00…". */
  const formatDateX = makeDateAxisFormatter(data.map((r) => r[x]));
  const formatCategoryX = (v: unknown, max = 18) =>
    formatDateX ? formatDateX(v) : truncateLabel(v, max);

  return (
    <figure className="mt-4">
      {title && (
        <figcaption className="mb-3 text-sm font-medium text-slate-700">{title}</figcaption>
      )}
      <div style={{ width: '100%', height: CHART_HEIGHT }}>
        <ResponsiveContainer width="100%" height="100%">
          {type === 'bar' ? (
            <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }} barCategoryGap="20%">
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey={x}
                tick={TICK}
                tickLine={false}
                axisLine={{ stroke: GRID }}
                tickFormatter={(v: unknown) => formatCategoryX(v)}
                interval="preserveStartEnd"
                minTickGap={4}
              />
              <YAxis
                tick={TICK}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={formatY}
              />
              <Tooltip content={<ChartTooltip labelFormat={(v) => formatCategoryX(v)} />} cursor={{ fill: 'rgba(79,70,229,0.06)' }} />
              {multi && <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={8} />}
              {seriesKeys.map((k, i) => (
                <Bar
                  key={k}
                  dataKey={k}
                  fill={colorAt(i)}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={48}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          ) : type === 'line' ? (
            <LineChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey={x}
                tick={TICK}
                tickLine={false}
                axisLine={{ stroke: GRID }}
                tickFormatter={(v: unknown) => formatCategoryX(v, 14)}
                interval="preserveStartEnd"
                minTickGap={16}
              />
              <YAxis
                tick={TICK}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={formatY}
              />
              <Tooltip content={<ChartTooltip labelFormat={(v) => formatCategoryX(v)} />} cursor={{ stroke: '#94a3b8', strokeWidth: 1 }} />
              {multi && <Legend wrapperStyle={legendStyle} iconType="circle" iconSize={8} />}
              {seriesKeys.map((k, i) => (
                <Line
                  key={k}
                  type="monotone"
                  dataKey={k}
                  stroke={colorAt(i)}
                  strokeWidth={2}
                  dot={data.length <= 24 ? { r: 3, strokeWidth: 0, fill: colorAt(i) } : false}
                  activeDot={{ r: 5, strokeWidth: 2, stroke: '#ffffff' }}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          ) : (
            <ScatterChart margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis
                type="number"
                dataKey={x}
                name={x}
                tick={TICK}
                tickLine={false}
                axisLine={{ stroke: GRID }}
                tickFormatter={formatX}
              />
              <YAxis
                type="number"
                dataKey={y}
                name={y}
                tick={TICK}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={formatY}
              />
              <ZAxis range={[80, 80]} />
              <Tooltip content={<ChartTooltip labelFormat={(v) => formatCategoryX(v)} />} cursor={{ strokeDasharray: '3 3' }} />
              <Scatter
                data={plain}
                fill={colorAt(0)}
                fillOpacity={0.75}
                stroke="#ffffff"
                strokeWidth={2}
                isAnimationActive={false}
              />
            </ScatterChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/** Hero number: a single figure needs no plot. */
function KpiCard({ chart, rows }: { chart: ChartSpec; rows: Row[] }) {
  const first = rows[0];
  if (!first) return null;

  const key = chart.y && chart.y in first ? chart.y : Object.keys(first)[0];
  if (!key) return null;

  const raw = first[key];
  const n = toNumber(raw);
  const display =
    n !== null ? formatNumber(n) : raw === null || raw === undefined ? '—' : String(raw);

  return (
    <div className="mt-4 rounded-xl border border-accent-100 bg-gradient-to-br from-accent-50 to-white px-5 py-5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-accent-700">
        {chart.title ?? key.replace(/_/g, ' ')}
      </div>
      <div className="mt-1.5 text-4xl font-semibold tabular-nums tracking-tight text-slate-900">
        {display}
      </div>
      <div className="mt-1 font-mono text-[11px] text-slate-500">{key}</div>
    </div>
  );
}
