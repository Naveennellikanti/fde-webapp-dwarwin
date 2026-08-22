'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, RotateCw, User } from 'lucide-react';
import * as api from '@/lib/api';
import type { AppConfig, JoinHint, TableInfo, TableQualityInfo, Turn } from '@/lib/types';
import Sidebar from '@/components/Sidebar';
import AskBox from '@/components/AskBox';
import AnswerCard from '@/components/AnswerCard';
import ThinkingCard from '@/components/ThinkingCard';
import EmptyState from '@/components/EmptyState';
import SettingsPanel from '@/components/SettingsPanel';

function errMessage(e: unknown): string {
  if (e instanceof api.ApiError) return e.message;
  if (e instanceof Error && e.message) return e.message;
  return 'Something went wrong. Please try again.';
}

let turnSeq = 0;
const nextTurnId = () => `turn-${++turnSeq}`;

export default function Page() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);

  const [tables, setTables] = useState<TableInfo[]>([]);
  const [joins, setJoins] = useState<JoinHint[]>([]);
  const [quality, setQuality] = useState<TableQualityInfo[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [removingTable, setRemovingTable] = useState<string | null>(null);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [asking, setAsking] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hasSessionKey, setHasSessionKey] = useState(false);

  const threadRef = useRef<HTMLDivElement>(null);
  const bootstrapped = useRef(false);

  // ---- Session bootstrap (once on mount, StrictMode-safe) -----------------
  const bootstrap = useCallback(async () => {
    setSessionError(null);
    try {
      const s = await api.createSession();
      setSessionId(s.session_id);
    } catch (e) {
      setSessionError(errMessage(e));
    }
    // /config is informational — a failure must not block the app.
    try {
      setConfig(await api.getConfig());
    } catch {
      /* leave the badge showing "connecting…" */
    }
  }, []);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    void bootstrap();
  }, [bootstrap]);

  // Keep the newest turn in view.
  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, asking]);

  // ---- Upload -------------------------------------------------------------
  const handleFiles = useCallback(
    async (files: File[]) => {
      if (!sessionId) {
        setUploadError('No active session yet. Reconnect and try again.');
        return;
      }
      setUploading(true);
      setUploadError(null);
      try {
        const res = await api.uploadFiles(sessionId, files);
        setTables(res.tables);
        setJoins(res.joins);
        setQuality(res.quality ?? []);
      } catch (e) {
        setUploadError(errMessage(e));
      } finally {
        setUploading(false);
      }
    },
    [sessionId]
  );

  // ---- Remove one table ---------------------------------------------------
  const handleRemoveTable = useCallback(
    async (table: string) => {
      if (!sessionId || removingTable) return;
      setRemovingTable(table);
      setUploadError(null);
      try {
        // The server recomputes joins and the quality profile, since both describe a
        // schema that just changed — so the whole schema response replaces local state
        // rather than filtering the table out client-side.
        const res = await api.dropTable(sessionId, table);
        setTables(res.tables);
        setJoins(res.joins);
        setQuality(res.quality ?? []);
      } catch (e) {
        setUploadError(errMessage(e));
      } finally {
        setRemovingTable(null);
      }
    },
    [sessionId, removingTable]
  );

  // ---- Ask ----------------------------------------------------------------
  const handleAsk = useCallback(
    async (question: string) => {
      if (!sessionId || asking) return;

      const id = nextTurnId();
      setTurns((prev) => [...prev, { id, question, response: null, transportError: null }]);
      setAsking(true);

      try {
        const res = await api.ask(sessionId, question);
        setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, response: res } : t)));

        // The badge is fetched once at startup, so it goes stale if the backend
        // resolves differently later — `auto` falling back to hosted, or the setting
        // being changed elsewhere. The answer reports which backend actually served
        // it, so reconcile rather than let the sidebar claim one and the footer
        // another.
        const served = res.backend_used?.split(':')[0];
        if (served && config && served !== config.backend) {
          try {
            setConfig(await api.getConfig());
          } catch {
            /* the answer is already shown; a stale badge is not worth surfacing */
          }
        }
      } catch (e) {
        const message = errMessage(e);
        setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, transportError: message } : t)));
      } finally {
        setAsking(false);
      }
    },
    [sessionId, asking, config]
  );

  const hasData = tables.length > 0;
  const ready = Boolean(sessionId) && hasData;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        config={config}
        tables={tables}
        joins={joins}
        quality={quality}
        onFiles={handleFiles}
        uploading={uploading}
        uploadDisabled={!sessionId}
        uploadError={uploadError}
        onOpenSettings={() => setSettingsOpen(true)}
        onRemoveTable={handleRemoveTable}
        removingTable={removingTable}
      />

      {settingsOpen && config && (
        <SettingsPanel
          config={config}
          onConfigChange={setConfig}
          onClose={() => setSettingsOpen(false)}
          sessionId={sessionId}
          hasSessionKey={hasSessionKey}
          onSessionKeyChange={setHasSessionKey}
        />
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        {sessionError && (
          <div
            role="alert"
            className="flex items-center gap-2.5 border-b border-red-200 bg-red-50 px-8 py-2.5 text-sm text-red-800"
          >
            <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />
            <span className="min-w-0 flex-1">
              Could not start a session: {sessionError}
            </span>
            <button
              type="button"
              onClick={() => void bootstrap()}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-700 transition hover:bg-red-100"
            >
              <RotateCw className="h-3 w-3" />
              Retry
            </button>
          </div>
        )}

        {/* Conversation thread */}
        <div ref={threadRef} className="scroll-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-4xl space-y-6 px-8 py-8">
            {turns.length === 0 ? (
              <EmptyState hasData={hasData} />
            ) : (
              turns.map((t) => (
                <section key={t.id} className="space-y-3">
                  {/* Question */}
                  <div className="flex items-start justify-end gap-2.5">
                    <p className="max-w-[80%] whitespace-pre-wrap rounded-xl rounded-tr-sm bg-accent-600 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
                      {t.question}
                    </p>
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-200 text-slate-500">
                      <User className="h-3.5 w-3.5" />
                    </span>
                  </div>

                  {/* Answer */}
                  {t.response ? (
                    <AnswerCard res={t.response} onAsk={handleAsk} />
                  ) : t.transportError ? (
                    <div
                      role="alert"
                      className="animate-fade-up rounded-xl border border-red-200 bg-red-50/70 p-5 shadow-card"
                    >
                      <div className="flex items-start gap-2.5">
                        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-red-100 text-red-700">
                          <AlertCircle className="h-4 w-4" />
                        </span>
                        <div className="min-w-0">
                          <h3 className="text-sm font-semibold text-red-900">Request failed</h3>
                          <p className="mt-1 break-words text-sm leading-relaxed text-red-900/90">
                            {t.transportError}
                          </p>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <ThinkingCard />
                  )}
                </section>
              ))
            )}
          </div>
        </div>

        <AskBox
          onSubmit={handleAsk}
          loading={asking}
          ready={ready}
          showExamples={turns.length === 0}
        />
      </main>
    </div>
  );
}
