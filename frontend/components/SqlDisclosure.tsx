'use client';

import { useEffect, useState } from 'react';
import { Check, ChevronRight, Code2, Copy } from 'lucide-react';

export default function SqlDisclosure({
  sql,
  defaultOpen = false,
  label = 'View SQL',
}: {
  sql: string;
  defaultOpen?: boolean;
  label?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${
            open ? 'rotate-90' : ''
          }`}
        />
        <Code2 className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        {label}
        <span className="ml-auto text-[11px] font-normal text-slate-400">
          {open ? 'hide' : 'auditable'}
        </span>
      </button>

      {open && (
        <div className="relative border-t border-slate-200 p-2.5">
          <CopyButton text={sql} />
          <pre className="code-block">{sql}</pre>
        </div>
      )}
    </div>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // Clipboard API unavailable (insecure origin) — fall back to a selection copy.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        setCopied(true);
      } catch {
        /* give up silently — the SQL is still selectable on screen */
      }
      document.body.removeChild(ta);
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy SQL to clipboard"
      className="absolute right-4 top-4 z-10 inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] font-medium text-slate-200 transition hover:bg-slate-700"
    >
      {copied ? (
        <>
          <Check className="h-3 w-3" /> Copied
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" /> Copy
        </>
      )}
    </button>
  );
}
