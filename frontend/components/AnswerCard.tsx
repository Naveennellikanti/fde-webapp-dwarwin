'use client';

import { AlertTriangle, Inbox, Sparkles, XCircle } from 'lucide-react';
import type { AskResponse } from '@/lib/types';
import { formatNumber } from '@/lib/format';
import ChartView from './ChartView';
import DataTable from './DataTable';
import SqlDisclosure from './SqlDisclosure';
import AttemptsDisclosure from './AttemptsDisclosure';
import { AnswerNotices, ClarificationCard, ConfidenceBadge } from './AnswerMeta';

export default function AnswerCard({
  res,
  onAsk,
}: {
  res: AskResponse;
  /** Lets a clarification option re-ask the question in one click. */
  onAsk?: (question: string) => void;
}) {
  const { status } = res;

  if (status === 'cannot_answer') {
    return (
      <StateCard
        tone="amber"
        icon={<AlertTriangle className="h-4 w-4" />}
        heading="Can't answer from this data"
        body={res.answer}
        res={res}
        showSql={false}
      />
    );
  }

  if (status === 'error') {
    return (
      <StateCard
        tone="red"
        icon={<XCircle className="h-4 w-4" />}
        heading="Query failed"
        body={res.answer}
        res={res}
        showSql
      />
    );
  }

  if (status === 'empty') {
    return (
      <StateCard
        tone="slate"
        icon={<Inbox className="h-4 w-4" />}
        heading="No rows matched"
        body={res.answer || 'The query ran successfully but returned no rows.'}
        res={res}
        showSql
      />
    );
  }

  if (status === 'needs_clarification') {
    return <ClarificationCard res={res} onChoose={(q) => onAsk?.(q)} />;
  }

  // status === "ok"
  return (
    <article className="card animate-fade-up p-5">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent-50 text-accent-600">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        <p className="whitespace-pre-wrap text-[15px] font-medium leading-relaxed text-slate-900">
          {res.answer}
        </p>
      </div>

      <AnswerNotices res={res} />

      <ChartView chart={res.chart} rows={res.rows} />

      <DataTable columns={res.columns} rows={res.rows} truncated={res.truncated} />

      {res.sql && <SqlDisclosure sql={res.sql} />}
      <AttemptsDisclosure attempts={res.attempts} />

      <CardFooter res={res} />
    </article>
  );
}

function StateCard({
  tone,
  icon,
  heading,
  body,
  res,
  showSql,
}: {
  tone: 'amber' | 'red' | 'slate';
  icon: React.ReactNode;
  heading: string;
  body: string;
  res: AskResponse;
  showSql: boolean;
}) {
  const tones = {
    amber: {
      wrap: 'border-amber-200 bg-amber-50/70',
      badge: 'bg-amber-100 text-amber-700',
      head: 'text-amber-900',
      text: 'text-amber-900/90',
    },
    red: {
      wrap: 'border-red-200 bg-red-50/70',
      badge: 'bg-red-100 text-red-700',
      head: 'text-red-900',
      text: 'text-red-900/90',
    },
    slate: {
      wrap: 'border-slate-200 bg-slate-50',
      badge: 'bg-slate-200 text-slate-600',
      head: 'text-slate-900',
      text: 'text-slate-600',
    },
  }[tone];

  return (
    <article className={`animate-fade-up rounded-xl border p-5 shadow-card ${tones.wrap}`}>
      <div className="flex items-start gap-2.5">
        <span
          className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${tones.badge}`}
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className={`text-sm font-semibold ${tones.head}`}>{heading}</h3>
          <p className={`mt-1 whitespace-pre-wrap text-sm leading-relaxed ${tones.text}`}>{body}</p>
        </div>
      </div>

      {showSql && res.sql && <SqlDisclosure sql={res.sql} defaultOpen={res.status === 'error'} />}
      <AttemptsDisclosure attempts={res.attempts} />
      <CardFooter res={res} />
    </article>
  );
}

function CardFooter({ res }: { res: AskResponse }) {
  const bits: string[] = [];
  if (res.backend_used) bits.push(res.backend_used);
  bits.push(`${formatNumber(res.tokens_used)} tokens`);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-slate-200/70 pt-2">
      {res.confidence && (
        <ConfidenceBadge level={res.confidence} reasons={res.confidence_reasons} />
      )}
      <p className="font-mono text-[11px] text-slate-400">{bits.join(' · ')}</p>
    </div>
  );
}
