'use client';

import { useCallback, useRef, useState } from 'react';
import { AlertCircle, Loader2, UploadCloud } from 'lucide-react';

const ACCEPT = '.csv,.xlsx,.xls,.tsv,.txt';

interface Props {
  onFiles: (files: File[]) => void;
  uploading: boolean;
  disabled: boolean;
  error: string | null;
  maxUploadMb: number | null;
}

export default function UploadZone({
  onFiles,
  uploading,
  disabled,
  error,
  maxUploadMb,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);

  const busy = uploading || disabled;

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      if (busy) return;
      const files = Array.from(e.dataTransfer.files ?? []);
      if (files.length) onFiles(files);
    },
    [busy, onFiles]
  );

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-disabled={busy}
        aria-label="Upload data files"
        onClick={() => !busy && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !busy) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepth.current += 1;
          if (!busy) setDragging(true);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={(e) => {
          e.preventDefault();
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) {
            dragDepth.current = 0;
            setDragging(false);
          }
        }}
        onDrop={handleDrop}
        className={[
          'flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition',
          busy
            ? 'cursor-not-allowed border-slate-200 bg-slate-50'
            : 'cursor-pointer hover:border-accent-400 hover:bg-accent-50/50',
          dragging
            ? 'border-accent-500 bg-accent-50'
            : 'border-slate-300 bg-white',
        ].join(' ')}
      >
        {uploading ? (
          <>
            <Loader2 className="h-6 w-6 animate-spin text-accent-600" />
            <p className="text-sm font-medium text-slate-700">Uploading…</p>
            <p className="text-xs text-slate-500">Profiling columns and inferring types</p>
          </>
        ) : (
          <>
            <UploadCloud
              className={dragging ? 'h-6 w-6 text-accent-600' : 'h-6 w-6 text-slate-400'}
            />
            <p className="text-sm font-medium text-slate-700">
              Drop files here or <span className="text-accent-600">browse</span>
            </p>
            <p className="text-xs text-slate-500">
              CSV, TSV, TXT, XLSX, XLS · multiple files supported
              {maxUploadMb ? ` · up to ${maxUploadMb} MB each` : ''}
            </p>
          </>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          // Reset so re-selecting the same file still fires a change event.
          e.target.value = '';
        }}
      />

      {error && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs text-red-800"
        >
          <AlertCircle className="mt-px h-4 w-4 shrink-0 text-red-500" />
          <span className="break-words">{error}</span>
        </div>
      )}
    </div>
  );
}
