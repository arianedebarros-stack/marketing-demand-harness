"use client";

import { useState } from "react";
import { brandChips, canSendMessage, typeChips } from "@/lib/demand";
import type { AppConfig, ChatMessage, RequestView } from "@/lib/types";

interface ChatProps {
  view: RequestView;
  messages: ChatMessage[];
  config: AppConfig;
  busy: boolean;
  error: string | null;
  onSend: (message: string) => Promise<void> | void;
  onConfirmType: (taskType: string) => Promise<void> | void;
}

function Chip({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="rounded-full border border-indigo-300 bg-white px-3 py-1 text-sm text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
    >
      {label}
    </button>
  );
}

/** Chat da demanda (§13, tela 1): histórico, chips de marca/tipo e campo de resposta. */
export function Chat({ view, messages, config, busy, error, onSend, onConfirmType }: ChatProps) {
  const [draft, setDraft] = useState("");
  const status = view.demand.status;
  const open = canSendMessage(status);
  const brands = brandChips(view, config);
  const types = typeChips(view, config);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    await onSend(text);
    setDraft("");
  }

  return (
    <div className="flex h-full flex-col rounded-lg border border-slate-200 bg-white">
      <ol aria-label="Conversa" className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((message) => (
          <li
            key={message.id}
            className={message.role === "requester" ? "flex justify-end" : "flex justify-start"}
          >
            <p
              className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                message.role === "requester"
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-100 text-slate-800"
              }`}
            >
              {message.text}
            </p>
          </li>
        ))}
        {busy && (
          <li className="text-sm text-slate-500" aria-live="polite">
            Interpretando…
          </li>
        )}
      </ol>

      <div className="space-y-2 border-t border-slate-200 p-4">
        {types.length > 0 && (
          <div>
            <p className="mb-1 text-sm font-medium">Confirme o tipo da demanda:</p>
            <div className="flex flex-wrap gap-2">
              {types.map((type) => (
                <Chip key={type} label={type} disabled={busy} onClick={() => onConfirmType(type)} />
              ))}
            </div>
          </div>
        )}
        {brands.length > 0 && open && (
          <div>
            <p className="mb-1 text-sm font-medium">Marca:</p>
            <div className="flex flex-wrap gap-2">
              {brands.map((brand) => (
                <Chip key={brand} label={brand} disabled={busy} onClick={() => onSend(brand)} />
              ))}
            </div>
          </div>
        )}
        {status === "PENDING_APPROVAL" && (
          <p className="text-sm text-slate-600">
            Briefing completo, aguardando aprovação. Uma nova mensagem faz a demanda voltar para
            validação.
          </p>
        )}
        {error && (
          <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </p>
        )}
        <form onSubmit={submit} className="flex gap-2">
          <label htmlFor="chat-input" className="sr-only">
            Sua mensagem
          </label>
          <textarea
            id="chat-input"
            rows={2}
            value={draft}
            disabled={!open || busy}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={open ? "Responda aqui…" : "Esta demanda não aceita novas mensagens."}
            className="flex-1 resize-none rounded border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50"
          />
          <button
            type="submit"
            disabled={!open || busy || !draft.trim()}
            className="rounded bg-indigo-600 px-4 text-sm font-medium text-white disabled:opacity-50"
          >
            Enviar
          </button>
        </form>
      </div>
    </div>
  );
}
