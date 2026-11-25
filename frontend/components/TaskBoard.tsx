"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AuditTable } from "@/components/AuditTable";
import { completeTask, getConfig, getRequest, listTasks, resolveDependency } from "@/lib/api";
import { formatDate, memberName, newestFirst, taskStatus, type TaskStatusLabel } from "@/lib/demand";
import type { AppConfig, AuditEntry, Task } from "@/lib/types";

const message = (exc: unknown) => (exc instanceof Error ? exc.message : String(exc));

const STATUS_STYLES: Record<TaskStatusLabel, string> = {
  Aberta: "bg-sky-100 text-sky-800",
  Bloqueada: "bg-amber-100 text-amber-800",
  Concluída: "bg-emerald-100 text-emerald-800",
};

function StatusBadge({ task }: { task: Task }) {
  const label = taskStatus(task);
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[label]}`}>
      {label}
    </span>
  );
}

function TaskDetail({
  task,
  config,
  onChange,
}: {
  task: Task;
  config: AppConfig;
  onChange: (task: Task) => void;
}) {
  const [history, setHistory] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const view = await getRequest(task.request_id);
      setHistory(newestFirst(view.audit));
    } catch (exc) {
      setError(message(exc));
    }
  }, [task.request_id]);

  useEffect(() => {
    setHistory(null);
    setError(null);
    void loadHistory();
  }, [loadHistory]);

  async function run(action: () => Promise<Task>) {
    setBusy(true);
    setError(null);
    try {
      onChange(await action());
      await loadHistory();
    } catch (exc) {
      setError(message(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Detalhe da tarefa"
      className="space-y-4 rounded-lg border border-slate-200 bg-white p-4"
    >
      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-slate-500">{task.external_task_id}</span>
          <StatusBadge task={task} />
        </div>
        <h2 className="text-lg font-semibold">{task.title}</h2>
        <p className="text-sm text-slate-600">
          {task.assigned_to ? memberName(task.assigned_to, config) : "Responsável a definir"}
          {task.priority && ` · ${task.priority}`}
          {task.deadline && ` · prazo ${formatDate(task.deadline)}`}
        </p>
        <Link href={`/demandas/${task.request_id}`} className="text-sm text-indigo-700 hover:underline">
          Abrir a demanda
        </Link>
      </header>

      {error && (
        <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}

      <div>
        <h3 className="text-sm font-semibold">Dependências</h3>
        {task.dependencies.length === 0 ? (
          <p className="mt-1 text-sm text-slate-500">Nenhuma</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {task.dependencies.map((dep) => (
              <li key={dep.index} aria-label={dep.description} className="flex items-center gap-2">
                <span>{dep.description}</span>
                <span className="text-slate-500">{dep.owner}</span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                    dep.status === "Pendente"
                      ? "bg-amber-100 text-amber-800"
                      : "bg-emerald-100 text-emerald-800"
                  }`}
                >
                  {dep.status}
                </span>
                {dep.status === "Pendente" && task.status === "Aberta" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => run(() => resolveDependency(task.id, dep.index))}
                    className="rounded border border-indigo-300 px-2 py-0.5 text-xs text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
                  >
                    Resolver
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {task.status === "Aberta" && (
        <button
          type="button"
          disabled={busy}
          onClick={() => run(() => completeTask(task.id))}
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Concluir tarefa
        </button>
      )}

      <div>
        <h3 className="text-sm font-semibold">Briefing</h3>
        <pre className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-3 font-sans text-sm">
          {task.briefing}
        </pre>
      </div>

      <div>
        <h3 className="text-sm font-semibold">Histórico</h3>
        {history === null ? (
          <p className="mt-1 text-sm text-slate-500">Carregando histórico…</p>
        ) : (
          <AuditTable entries={history} label="Histórico" showRequest={false} />
        )}
      </div>
    </section>
  );
}

/** Quadro de tarefas (§13, tela 4): lista com status e detalhe com briefing e histórico. */
export function TaskBoard({ initialTaskId }: { initialTaskId?: number }) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [selected, setSelected] = useState<number | null>(initialTaskId ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([listTasks(), getConfig()])
      .then(([loaded, appConfig]) => {
        if (!active) return;
        setTasks(loaded);
        setConfig(appConfig);
      })
      .catch((exc: unknown) => active && setError(message(exc)));
    return () => {
      active = false;
    };
  }, []);

  const replace = (updated: Task) =>
    setTasks((current) => current?.map((t) => (t.id === updated.id ? updated : t)) ?? null);

  if (error) {
    return (
      <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">
        {error}
      </p>
    );
  }
  if (!tasks || !config) return <p className="text-sm text-slate-500">Carregando tarefas…</p>;

  const current = tasks.find((t) => t.id === selected) ?? null;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Quadro de tarefas</h1>
      {tasks.length === 0 ? (
        <p className="text-sm text-slate-500">Nenhuma tarefa criada ainda.</p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table aria-label="Tarefas" className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs text-slate-500">
                  <th className="px-3 py-2 font-medium">Tarefa</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Responsável</th>
                  <th className="px-3 py-2 font-medium">Prioridade</th>
                  <th className="px-3 py-2 font-medium">Prazo</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr
                    key={task.id}
                    aria-selected={task.id === selected}
                    className={`border-b border-slate-100 last:border-0 ${
                      task.id === selected ? "bg-indigo-50" : ""
                    }`}
                  >
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => setSelected(task.id)}
                        className="text-left font-medium text-indigo-700 hover:underline"
                      >
                        {task.title}
                      </button>
                      <div className="font-mono text-xs text-slate-500">{task.external_task_id}</div>
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge task={task} />
                    </td>
                    <td className="px-3 py-2">
                      {task.assigned_to ? memberName(task.assigned_to, config) : "A definir"}
                    </td>
                    <td className="px-3 py-2">{task.priority ?? "—"}</td>
                    <td className="px-3 py-2 tabular-nums">
                      {task.deadline ? formatDate(task.deadline) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {current ? (
            <TaskDetail key={current.id} task={current} config={config} onChange={replace} />
          ) : (
            <p className="text-sm text-slate-500">Escolha uma tarefa para ver o briefing e o histórico.</p>
          )}
        </div>
      )}
    </div>
  );
}
