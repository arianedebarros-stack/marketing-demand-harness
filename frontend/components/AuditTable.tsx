import Link from "next/link";
import { ACTOR_LABELS, auditValue, formatDateTime } from "@/lib/demand";
import type { AuditEntry } from "@/lib/types";

/** Tabela de audit na ordem recebida (quem chama ordena, §13 tela 5). */
export function AuditTable({
  entries,
  label,
  showRequest = true,
}: {
  entries: AuditEntry[];
  label: string;
  showRequest?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs text-slate-500">
            <th className="py-1.5 pr-3 font-medium">#</th>
            <th className="py-1.5 pr-3 font-medium">Quando</th>
            <th className="py-1.5 pr-3 font-medium">Ator</th>
            <th className="py-1.5 pr-3 font-medium">Ação</th>
            {showRequest && <th className="py-1.5 pr-3 font-medium">Origem</th>}
            <th className="py-1.5 font-medium">Valores</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const before = auditValue(entry.previous_value);
            const after = auditValue(entry.new_value);
            return (
              <tr key={entry.id} className="border-b border-slate-100 align-top last:border-0">
                <td data-testid="audit-id" className="py-1.5 pr-3 tabular-nums text-slate-500">
                  {entry.id}
                </td>
                <td className="whitespace-nowrap py-1.5 pr-3 tabular-nums">
                  {formatDateTime(entry.timestamp)}
                </td>
                <td className="py-1.5 pr-3">{ACTOR_LABELS[entry.actor] ?? entry.actor}</td>
                <td data-testid="audit-action" className="py-1.5 pr-3 font-mono text-xs">
                  {entry.action}
                </td>
                {showRequest && (
                  <td className="whitespace-nowrap py-1.5 pr-3">
                    {entry.request_id && (
                      <Link
                        href={`/demandas/${entry.request_id}`}
                        className="text-indigo-700 hover:underline"
                      >
                        Demanda {entry.request_id.slice(0, 8)}
                      </Link>
                    )}
                    {entry.task_id !== null && (
                      <Link
                        href={`/tarefas?tarefa=${entry.task_id}`}
                        className="ml-2 text-indigo-700 hover:underline"
                      >
                        Tarefa #{entry.task_id}
                      </Link>
                    )}
                  </td>
                )}
                <td className="max-w-md py-1.5 font-mono text-xs text-slate-700">
                  {before && (
                    <div className="break-all">
                      <span className="text-slate-400">antes </span>
                      {before}
                    </div>
                  )}
                  {after && <div className="break-all">{after}</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
