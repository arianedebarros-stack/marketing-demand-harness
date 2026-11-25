"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Chat } from "@/components/Chat";
import { DemandSheet } from "@/components/DemandSheet";
import { confirmType, getConfig, getMessages, getRequest, sendAnswer } from "@/lib/api";
import type { AppConfig, ChatMessage, RequestView } from "@/lib/types";

const message = (exc: unknown) => (exc instanceof Error ? exc.message : String(exc));

/** Página da demanda: chat à esquerda, ficha ao lado (§13, telas 1 e 2). */
export function DemandWorkspace({ requestId }: { requestId: string }) {
  const [view, setView] = useState<RequestView | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([getRequest(requestId), getMessages(requestId), getConfig()])
      .then(([loaded, history, appConfig]) => {
        if (!active) return;
        setView(loaded);
        setMessages(history);
        setConfig(appConfig);
      })
      .catch((exc: unknown) => active && setLoadError(message(exc)));
    return () => {
      active = false;
    };
  }, [requestId]);

  const run = useCallback(
    async (action: () => Promise<RequestView>) => {
      setBusy(true);
      setActionError(null);
      try {
        const updated = await action();
        setView(updated);
        setMessages(await getMessages(requestId));
      } catch (exc) {
        setActionError(message(exc));
      } finally {
        setBusy(false);
      }
    },
    [requestId],
  );

  if (loadError) {
    return (
      <div className="space-y-3">
        <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">
          {loadError}
        </p>
        <Link href="/" className="text-sm text-indigo-700 underline">
          Voltar para nova demanda
        </Link>
      </div>
    );
  }
  if (!view || !config) return <p className="text-sm text-slate-500">Carregando demanda…</p>;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <div className="lg:sticky lg:top-6 lg:h-[calc(100vh-7rem)]">
        <Chat
          view={view}
          messages={messages}
          config={config}
          busy={busy}
          error={actionError}
          onSend={(text) => run(() => sendAnswer(requestId, text))}
          onConfirmType={(type) => run(() => confirmType(requestId, type))}
        />
      </div>
      <DemandSheet view={view} config={config} />
    </div>
  );
}
