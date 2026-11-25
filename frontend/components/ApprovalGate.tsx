"use client";

import { useState } from "react";
import { OriginTag } from "@/components/DemandSheet";
import {
  DUPLICATE_CRITERIA_LABELS,
  formatDate,
  gateForm,
  gatePatch,
  memberName,
  priorityLevels,
  type GateForm,
} from "@/lib/demand";
import type { AppConfig, DemandPatch, DuplicateCandidate, RequestView } from "@/lib/types";

interface ApprovalGateProps {
  view: RequestView;
  config: AppConfig;
  busy: boolean;
  error: string | null;
  /** Tarefa parecida: da triagem (`duplicate_of`) ou do 409 do `approve`. */
  duplicate: DuplicateCandidate | null;
  onApprove: (forceNew: boolean) => void;
  onSave: (patch: DemandPatch) => Promise<boolean>;
  onCancel: () => void;
  onLinkExisting: (taskId: number) => void;
}

const BUTTON = "rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50";
const PRIMARY = `${BUTTON} bg-indigo-600 text-white hover:bg-indigo-700`;
const SECONDARY = `${BUTTON} border border-slate-300 bg-white hover:bg-slate-50`;
const DANGER = `${BUTTON} border border-red-300 bg-white text-red-700 hover:bg-red-50`;

function DuplicateAlert({
  duplicate,
  busy,
  onUseExisting,
  onCreateNew,
}: {
  duplicate: DuplicateCandidate;
  busy: boolean;
  onUseExisting: () => void;
  onCreateNew: () => void;
}) {
  const criteria = duplicate.criteria.map((c) => DUPLICATE_CRITERIA_LABELS[c] ?? c).join(", ");
  return (
    <div
      role="alert"
      aria-label="Possível duplicidade"
      className="space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
    >
      <p>
        Já existe uma tarefa aberta parecida:{" "}
        <strong>
          {duplicate.title} (#{duplicate.task_id})
        </strong>
        {criteria && ` — ${criteria}.`}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={onUseExisting} className={PRIMARY}>
          Usar existente
        </button>
        <button type="button" disabled={busy} onClick={onCreateNew} className={SECONDARY}>
          Criar nova
        </button>
      </div>
    </div>
  );
}

function EditForm({
  view,
  config,
  busy,
  onSave,
  onClose,
}: {
  view: RequestView;
  config: AppConfig;
  busy: boolean;
  onSave: (patch: DemandPatch) => Promise<boolean>;
  onClose: () => void;
}) {
  const [initial] = useState<GateForm>(() => gateForm(view.demand));
  const [form, setForm] = useState<GateForm>(initial);
  const patch = gatePatch(initial, form);
  const changed = Object.keys(patch).length > 0;
  const set = (field: keyof GateForm) => (event: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) =>
    setForm({ ...form, [field]: event.target.value });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (changed && (await onSave(patch))) onClose();
  }

  const input = "mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm";
  return (
    <form onSubmit={submit} className="space-y-3 rounded border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs text-slate-600">
        O que você mudar aqui fica com origem Gestor. &quot;Automático&quot; devolve a decisão ao harness.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm font-medium">
          Prioridade
          <select value={form.priority} onChange={set("priority")} className={input}>
            <option value="">Automático (harness)</option>
            {priorityLevels(config).map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Responsável
          <select value={form.assigned_to} onChange={set("assigned_to")} className={input}>
            <option value="">Automático (harness)</option>
            {config.team.map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          Prazo
          <input type="date" value={form.deadline} onChange={set("deadline")} className={input} />
        </label>
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={busy || !changed} className={PRIMARY}>
          Salvar alterações
        </button>
        <button type="button" onClick={onClose} className={SECONDARY}>
          Descartar
        </button>
      </div>
    </form>
  );
}

/** Approval Gate (§13, tela 3): nada vira tarefa sem o clique em "Aprovar e criar" (§14). */
export function ApprovalGate(props: ApprovalGateProps) {
  const { view, config, busy, error, duplicate } = props;
  const [editing, setEditing] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const demand = view.demand;
  const retry = demand.status === "APPROVED";
  const origin = (field: string) => demand.field_origin[field] ?? null;
  const assignee = demand.assigned_to
    ? memberName(demand.assigned_to, config)
    : `A definir (${demand.approver ?? config.task_types.approver_default})`;
  const deadline = typeof demand.deadline === "string" ? formatDate(demand.deadline) : "—";

  const rows: { label: string; value: string; field?: string }[] = [
    { label: "Título", value: view.title || "—" },
    { label: "Responsável", value: assignee, field: "assigned_to" },
    { label: "Prioridade", value: demand.priority ?? "—", field: "priority" },
    { label: "Prazo", value: deadline, field: "deadline" },
    { label: "Briefing Score", value: `${demand.briefing_score}%` },
  ];

  return (
    <section
      aria-label="Approval Gate"
      className="space-y-4 rounded-lg border-2 border-indigo-300 bg-white p-4"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-indigo-700">Aprovação</h2>
      {retry && (
        <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-900">
          A demanda foi aprovada, mas a criação da tarefa falhou. Tente de novo.
        </p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <dt className="font-medium text-slate-600">{row.label}</dt>
            <dd className="flex items-center gap-2">
              <span className={row.label === "Título" ? "font-semibold" : ""}>{row.value}</span>
              {row.field && <OriginTag origin={origin(row.field)} />}
            </dd>
          </div>
        ))}
      </dl>

      {duplicate && (
        <DuplicateAlert
          duplicate={duplicate}
          busy={busy}
          onUseExisting={() => props.onLinkExisting(duplicate.task_id)}
          onCreateNew={() => props.onApprove(true)}
        />
      )}

      {error && (
        <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </p>
      )}

      {editing ? (
        <EditForm
          view={view}
          config={config}
          busy={busy}
          onSave={props.onSave}
          onClose={() => setEditing(false)}
        />
      ) : confirmingCancel ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>Cancelar esta demanda? Ela não poderá ser retomada.</span>
          <button type="button" disabled={busy} onClick={props.onCancel} className={DANGER}>
            Confirmar cancelamento
          </button>
          <button type="button" onClick={() => setConfirmingCancel(false)} className={SECONDARY}>
            Voltar
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => props.onApprove(false)} className={PRIMARY}>
            {retry ? "Tentar criar de novo" : "Aprovar e criar"}
          </button>
          {!retry && (
            <button type="button" disabled={busy} onClick={() => setEditing(true)} className={SECONDARY}>
              Editar
            </button>
          )}
          <button type="button" disabled={busy} onClick={() => setConfirmingCancel(true)} className={DANGER}>
            Cancelar
          </button>
        </div>
      )}
    </section>
  );
}
