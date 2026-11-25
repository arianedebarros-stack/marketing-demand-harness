"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AuditTable } from "@/components/AuditTable";
import { listAudit } from "@/lib/api";
import type { AuditEntry } from "@/lib/types";

/** Linhas por página do GET /audit (D40). */
export const AUDIT_PAGE_SIZE = 100;

const message = (exc: unknown) => (exc instanceof Error ? exc.message : String(exc));

/** Registro (§13, tela 5): audit log em ordem decrescente, opcionalmente de uma demanda. */
export function AuditLog({ requestId }: { requestId?: string }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (before?: number) => {
      setBusy(true);
      setError(null);
      try {
        const page = await listAudit({ requestId, before, limit: AUDIT_PAGE_SIZE });
        setEntries((current) => (before === undefined ? page : [...(current ?? []), ...page]));
        setHasMore(page.length === AUDIT_PAGE_SIZE);
      } catch (exc) {
        setError(message(exc));
      } finally {
        setBusy(false);
      }
    },
    [requestId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Registro</h1>
          <p className="text-sm text-slate-600">
            {requestId
              ? `Tudo o que aconteceu com a demanda ${requestId.slice(0, 8)}, do mais recente ao mais antigo.`
              : "Tudo o que o harness, a IA e as pessoas fizeram, do mais recente ao mais antigo."}
          </p>
        </div>
        {requestId && (
          <Link href="/registro" className="text-sm text-indigo-700 hover:underline">
            Ver o registro completo
          </Link>
        )}
      </header>
      {error && (
        <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}
      {entries === null && !error && <p className="text-sm text-slate-500">Carregando registro…</p>}
      {entries !== null && entries.length === 0 && (
        <p className="text-sm text-slate-500">Nenhum registro.</p>
      )}
      {entries !== null && entries.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <AuditTable entries={entries} label="Registro" />
        </div>
      )}
      {hasMore && entries && (
        <button
          type="button"
          disabled={busy}
          onClick={() => load(entries.at(-1)?.id)}
          className="rounded border border-slate-300 bg-white px-4 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
        >
          Carregar mais
        </button>
      )}
    </div>
  );
}
