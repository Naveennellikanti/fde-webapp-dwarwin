'use client';

import { FileUp, MessageSquareText, ShieldCheck } from 'lucide-react';

const STEPS = [
  {
    icon: FileUp,
    title: 'Upload your files',
    body: 'Drop one or more CSV or Excel files in the sidebar. Columns, types and joins are detected automatically.',
  },
  {
    icon: MessageSquareText,
    title: 'Ask in plain English',
    body: 'Questions are translated to SQL and run against DuckDB — with a self-correcting retry loop when a query fails.',
  },
  {
    icon: ShieldCheck,
    title: 'Audit every answer',
    body: 'Each result ships with the exact SQL that produced it, so nothing is a black box.',
  },
];

export default function EmptyState({ hasData }: { hasData: boolean }) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-6 py-16 text-center">
      <h2 className="text-xl font-semibold text-slate-900">
        {hasData ? 'Your data is ready' : 'Start with your data'}
      </h2>
      <p className="mt-1.5 text-sm text-slate-500">
        {hasData
          ? 'Ask a question below, or pick one of the examples to see it in action.'
          : 'Upload a spreadsheet to begin. Nothing leaves your machine except the schema.'}
      </p>

      <ul className="mt-8 grid w-full gap-3 text-left sm:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="card p-4">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-50 text-accent-600">
              <s.icon className="h-3.5 w-3.5" />
            </span>
            <h3 className="mt-2.5 text-[13px] font-semibold text-slate-900">
              <span className="mr-1 text-slate-300">{i + 1}.</span>
              {s.title}
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">{s.body}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
