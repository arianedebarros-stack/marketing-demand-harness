"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApprovalGate } from "@/components/ApprovalGate";
import { Chat } from "@/components/Chat";
import { DemandSheet } from "@/components/DemandSheet";
import {
  approve,
  cancelRequest,
  confirmType,
  duplicateConflict,
  getConfig,
  getMessages,
  getRequest,
  linkExisting,
  patchRequest,
  sendAnswer,
} from "@/lib/api";
import { showsApprovalGate } from "@/lib/demand";
import type {
  AppConfig,
  ChatMessage,
  DemandPatch,
  DuplicateCandidate,
  RequestView,
} from "@/lib/types";

const message = (exc: unknown) => (exc instanceof Error ? exc.message : String(exc));

/** Resultado do gate: tarefa criada ou vínculo com a tarefa existente. */
function Outcome({ view }: { view: RequestView }) {
  const { status, external_task_id: external } = view.demand;
  if (!external) return null;
  const text =
    status === "TASK_CREATED"
      ? `Tarefa criada: ${external}`
      : status === "CANCELLED"
        ? `Vinculada à tarefa existente ${external}`
        : null;
  if (!text) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
    >
      <strong>{text}</strong>
      <Link href="/tarefas" className="text-indigo-700 hover:underline">
        Ver no quadro de tarefas
      </Link>
    </div>
  );
}

/** Página da demanda: chat à esquerda, ficha ao lado (§13, telas 1 e 2). */
export function DemandWorkspace({ requestId }: { requestId: string }) {
  const [view, setView] = useState<RequestView | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<DuplicateCandidate | null>(null);
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

  /** Ações do Approval Gate: o erro fica no gate; o 409 de duplicidade abre o alerta. */
  const runGate = useCallback(async (action: () => Promise<RequestView>): Promise<boolean> => {
    setBusy(true);
    setGateError(null);
    try {
      setView(await action());
      setConflict(null);
      return true;
    } catch (exc) {
      const duplicate = duplicateConflict(exc);
      if (duplicate) setConflict(duplicate.duplicate);
      else setGateError(message(exc));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

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
      <div className="space-y-4">
        {showsApprovalGate(view.demand.status) && (
          <ApprovalGate
            view={view}
            config={config}
            busy={busy}
            error={gateError}
            duplicate={conflict ?? view.demand.duplicate_of}
            onApprove={(forceNew) => void runGate(() => approve(requestId, forceNew))}
            onSave={(patch: DemandPatch) => runGate(() => patchRequest(requestId, patch))}
            onCancel={() => void runGate(() => cancelRequest(requestId))}
            onLinkExisting={(taskId) => void runGate(() => linkExisting(requestId, taskId))}
          />
        )}
        <Outcome view={view} />
        <DemandSheet view={view} config={config} />
        <Link
          href={`/registro?demanda=${requestId}`}
          className="inline-block text-sm text-indigo-700 hover:underline"
        >
          Ver o registro desta demanda
        </Link>
      </div>
    </div>
  );
}
