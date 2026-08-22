/** Number / cell formatting shared by tables, KPI cards and chart axes. */

const INT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const DEC2 = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function isNumeric(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Coerce a cell to a number when it plausibly is one (DuckDB may send numeric strings). */
export function toNumber(v: unknown): number | null {
  if (isNumeric(v)) return v;
  if (typeof v === 'string') {
    const t = v.trim();
    if (t === '') return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** Thousands separators; 2 decimals when the value is fractional. */
export function formatNumber(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  return Number.isInteger(n) ? INT.format(n) : DEC2.format(n);
}

const UNITS: Array<{ div: number; suffix: string }> = [
  { div: 1_000_000_000, suffix: 'B' },
  { div: 1_000_000, suffix: 'M' },
  { div: 1_000, suffix: 'k' },
  { div: 1, suffix: '' },
];

/**
 * Build a tick formatter for one axis. The unit (k/M/B) is chosen ONCE from the
 * axis magnitude, so a single axis never mixes "4,000" with "12k".
 */
export function makeAxisFormatter(values: number[]): (n: number) => string {
  const max = values.reduce((m, v) => (Number.isFinite(v) ? Math.max(m, Math.abs(v)) : m), 0);
  const unit = UNITS.find((u) => max >= u.div * 10) ?? UNITS[UNITS.length - 1];

  return (n: number) => {
    if (!Number.isFinite(n)) return '';
    if (n === 0) return '0';
    if (unit.div === 1) {
      if (Math.abs(n) >= 1 || n === 0) return INT.format(Math.round(n * 100) / 100);
      return String(Math.round(n * 1000) / 1000);
    }
    const scaled = n / unit.div;
    // One decimal only when it carries information.
    const rounded = Math.round(scaled * 10) / 10;
    return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}${unit.suffix}`;
  };
}

/** Render any result-set cell as display text. */
export function formatCell(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (isNumeric(v)) return formatNumber(v);
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** Category-axis tick labels: keep them short enough to read. */
export function truncateLabel(v: unknown, max = 18): string {
  const s = v === null || v === undefined ? '' : String(v);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
