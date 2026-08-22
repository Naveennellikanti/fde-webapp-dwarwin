'use client';

import { useEffect, useRef, useState } from 'react';
import { CornerDownLeft, Loader2, Send } from 'lucide-react';

const EXAMPLES = [
  'What is the total revenue?',
  'Show revenue by region',
  'Revenue trend over time',
  'Top 5 reps by revenue',
];

interface Props {
  onSubmit: (question: string) => void;
  loading: boolean;
  ready: boolean;
  showExamples: boolean;
}

export default function AskBox({ onSubmit, loading, ready, showExamples }: Props) {
  const [value, setValue] = useState('');
  const taRef = useRef<HTMLTextAreaElement>(null);

  const disabled = !ready || loading;

  // Autosize the textarea up to a ceiling.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 168)}px`;
  }, [value]);

  useEffect(() => {
    if (ready && !loading) taRef.current?.focus();
  }, [ready, loading]);

  function submit(text: string) {
    const q = text.trim();
    if (!q || disabled) return;
    onSubmit(q);
    setValue('');
  }

  return (
    <div className="border-t border-slate-200 bg-white/95 px-8 py-4 backdrop-blur">
      <div className="mx-auto max-w-4xl">
        <div
          className={`flex items-end gap-2 rounded-xl border bg-white p-2 shadow-card transition ${
            disabled ? 'border-slate-200' : 'border-slate-300 focus-within:border-accent-500 focus-within:ring-2 focus-within:ring-accent-100'
          }`}
        >
          <textarea
            ref={taRef}
            rows={1}
            value={value}
            disabled={disabled}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submit(value);
              }
            }}
            placeholder={
              !ready
                ? 'Upload a CSV or Excel file to start asking questions…'
                : 'Ask anything about your data…  (Enter to send, Shift+Enter for a new line)'
            }
            aria-label="Ask a question about your data"
            className="max-h-[168px] min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 text-slate-900 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:text-slate-400"
          />
          <button
            type="button"
            onClick={() => submit(value)}
            disabled={disabled || !value.trim()}
            className="btn-primary h-9 shrink-0 px-3"
            aria-label="Send question"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>

        {!ready ? (
          <p className="mt-2 text-xs text-slate-500">
            No data loaded yet — drop a file in the sidebar to enable questions.
          </p>
        ) : showExamples ? (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] font-medium text-slate-400">Try:</span>
            {EXAMPLES.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => submit(q)}
                disabled={disabled}
                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 transition hover:border-accent-300 hover:bg-accent-50 hover:text-accent-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
        ) : (
          <p className="mt-2 flex items-center gap-1 text-[11px] text-slate-400">
            <CornerDownLeft className="h-3 w-3" />
            Enter to send · Shift+Enter for a new line
          </p>
        )}
      </div>
    </div>
  );
}
