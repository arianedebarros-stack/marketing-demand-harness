"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createRequest } from "@/lib/api";

/** Nova demanda (§13, tela 1): nome, departamento e o pedido em linguagem natural. */
export function NewRequest() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = Boolean(name.trim() && department.trim() && message.trim());

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const view = await createRequest({
        requesterName: name.trim(),
        department: department.trim(),
        message: message.trim(),
      });
      router.push(`/demandas/${view.demand.request_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setBusy(false);
    }
  }

  const input = "mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm";
  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-slate-200 bg-white p-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm font-medium">
          Seu nome
          <input value={name} onChange={(e) => setName(e.target.value)} className={input} />
        </label>
        <label className="block text-sm font-medium">
          Departamento
          <input
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            className={input}
          />
        </label>
      </div>
      <label className="block text-sm font-medium">
        O que você precisa?
        <textarea
          rows={4}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ex.: Preciso de uma arte da Krona para amanhã."
          className={input}
        />
      </label>
      {error && (
        <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={!ready || busy}
        className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {busy ? "Interpretando…" : "Enviar pedido"}
      </button>
    </form>
  );
}
