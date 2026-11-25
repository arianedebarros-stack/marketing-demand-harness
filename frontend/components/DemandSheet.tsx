import {
  currentStep,
  fieldRows,
  formatNumber,
  formatPercent,
  latestAssignment,
  latestPriority,
  memberName,
  ORIGIN_LABELS,
  STATUS_LABELS,
  STEPS,
} from "@/lib/demand";
import type { AppConfig, FieldOrigin, PriorityLevel, RequestView, ScoreBand } from "@/lib/types";

const BAND_STYLES: Record<ScoreBand, { bar: string; text: string }> = {
  Incompleto: { bar: "bg-red-500", text: "text-red-700" },
  Parcial: { bar: "bg-amber-500", text: "text-amber-700" },
  "Quase pronto": { bar: "bg-sky-500", text: "text-sky-700" },
  "Pronto para produção": { bar: "bg-emerald-600", text: "text-emerald-700" },
};

const PRIORITY_STYLES: Record<PriorityLevel, string> = {
  Crítica: "bg-red-100 text-red-800 ring-red-300",
  Alta: "bg-orange-100 text-orange-800 ring-orange-300",
  Normal: "bg-sky-100 text-sky-800 ring-sky-300",
  Baixa: "bg-slate-100 text-slate-700 ring-slate-300",
};

const ORIGIN_STYLES: Record<FieldOrigin, string> = {
  message: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  llm: "bg-violet-50 text-violet-700 ring-violet-200",
  rule: "bg-teal-50 text-teal-700 ring-teal-200",
  harness: "bg-slate-100 text-slate-700 ring-slate-200",
  manager: "bg-amber-50 text-amber-800 ring-amber-200",
  requester: "bg-sky-50 text-sky-700 ring-sky-200",
};

export function OriginTag({ origin }: { origin: FieldOrigin | null }) {
  if (!origin) return null;
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${ORIGIN_STYLES[origin]}`}
      title={`Origem: ${ORIGIN_LABELS[origin]}`}
    >
      {ORIGIN_LABELS[origin]}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const id = `sec-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 id={id} className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Stepper({ view }: { view: RequestView }) {
  const status = view.demand.status;
  const step = currentStep(status);
  return (
    <div>
      <ol aria-label="Etapas da demanda" className="flex flex-wrap gap-1">
        {STEPS.map((item, index) => {
          const done = step !== null && index < step;
          const active = index === step;
          const style = active
            ? "bg-indigo-600 text-white"
            : done
              ? "bg-indigo-100 text-indigo-800"
              : "bg-slate-100 text-slate-500";
          return (
            <li
              key={item.label}
              aria-current={active ? "step" : undefined}
              className={`flex-1 rounded px-2 py-1.5 text-center text-xs font-medium ${style}`}
            >
              {done ? "✓ " : ""}
              {item.label}
            </li>
          );
        })}
      </ol>
      {step === null ? (
        <p role="status" className="mt-2 rounded bg-red-50 px-3 py-2 text-sm text-red-800">
          Demanda fora do fluxo: <strong>{STATUS_LABELS[status]}</strong>
        </p>
      ) : (
        <p className="mt-2 text-sm text-slate-600">
          Estado atual: <strong>{STATUS_LABELS[status]}</strong>
        </p>
      )}
    </div>
  );
}

function Score({ view }: { view: RequestView }) {
  const score = view.demand.briefing_score;
  const style = BAND_STYLES[view.score_band];
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-3xl font-semibold tabular-nums">{score}%</span>
        <span className={`text-sm font-semibold ${style.text}`}>{view.score_band}</span>
      </div>
      <div
        role="meter"
        aria-label="Briefing Score"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score}
        className="mt-2 h-2 overflow-hidden rounded bg-slate-100"
      >
        <div className={`h-full ${style.bar}`} style={{ width: `${score}%` }} />
      </div>
    </div>
  );
}

function Fields({ view }: { view: RequestView }) {
  const rows = fieldRows(view.demand);
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.field}
            data-missing={row.missing}
            className={row.missing ? "bg-amber-50" : "border-b border-slate-100 last:border-0"}
          >
            <th scope="row" className="w-36 py-1.5 pr-2 text-left align-top font-medium text-slate-600">
              {row.label}
            </th>
            <td className="py-1.5 pr-2 align-top">
              {row.missing ? (
                <span className="font-medium text-amber-800">Faltando</span>
              ) : (
                <span className="whitespace-pre-wrap">{row.value}</span>
              )}
            </td>
            <td className="py-1.5 text-right align-top">
              {!row.missing && <OriginTag origin={row.origin} />}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Triage({ view, config }: { view: RequestView; config: AppConfig }) {
  const demand = view.demand;
  const priority = latestPriority(view.audit);
  const assignment = latestAssignment(view.audit);
  const triaged = priority !== null || demand.priority !== null;
  const level = demand.priority ?? priority?.level ?? null;
  const score = demand.priority_score ?? priority?.score ?? null;
  const assignee = demand.assigned_to
    ? memberName(demand.assigned_to, config)
    : `A definir (${demand.approver ?? config.task_types.approver_default})`;

  return (
    <section aria-label="Triagem" className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Triagem</h2>
      {!triaged && (
        <p className="mb-3 text-sm text-slate-500">
          A triagem roda quando o briefing chega a 100%: prioridade e responsável aparecem aqui.
        </p>
      )}
      {triaged && (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold">Prioridade</h3>
            <div className="mt-1 flex items-center gap-2">
              {level && (
                <span
                  className={`rounded px-2 py-0.5 text-sm font-semibold ring-1 ring-inset ${PRIORITY_STYLES[level]}`}
                >
                  {level}
                </span>
              )}
              {score !== null && (
                <span className="text-sm text-slate-600">
                  Pontuação <span className="tabular-nums">{formatNumber(score)}</span>
                </span>
              )}
              {demand.priority_locked && <OriginTag origin="manager" />}
            </div>
            {priority && priority.reasons.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
                {priority.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold">Responsável</h3>
            <p className="mt-1 text-sm">
              <strong>{assignee}</strong> {demand.assignment_locked && <OriginTag origin="manager" />}
            </p>
            {assignment?.reason && <p className="mt-1 text-sm text-slate-600">{assignment.reason}</p>}
            {assignment && assignment.loads.length > 0 && (
              <table aria-label="Cargas da equipe" className="mt-2 w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-500">
                    <th className="font-medium">Colaborador</th>
                    <th className="font-medium">Carga</th>
                  </tr>
                </thead>
                <tbody>
                  {assignment.loads.map((item) => (
                    <tr key={item.employee_id}>
                      <td className="py-0.5">{item.name}</td>
                      <td className="py-0.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded bg-slate-100">
                            <div
                              className="h-full bg-indigo-500"
                              style={{ width: `${Math.min(item.load, 1) * 100}%` }}
                            />
                          </div>
                          <span className="tabular-nums">{formatPercent(item.load)}</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold">Dependências</h3>
          {demand.dependencies.length === 0 ? (
            <p className="mt-1 text-sm text-slate-500">Nenhuma</p>
          ) : (
            <ul className="mt-1 space-y-1 text-sm">
              {demand.dependencies.map((dep) => (
                <li key={dep.dependency}>
                  <span>{dep.dependency}</span>{" "}
                  <span className="text-slate-500">({dep.owner})</span>{" "}
                  <span
                    className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                      dep.status === "Pendente"
                        ? "bg-amber-100 text-amber-800"
                        : "bg-emerald-100 text-emerald-800"
                    }`}
                  >
                    {dep.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="text-sm font-semibold">Arquivos</h3>
          {demand.required_files.length === 0 ? (
            <p className="mt-1 text-sm text-slate-500">Nenhum</p>
          ) : (
            <ul className="mt-1 space-y-1 text-sm">
              {demand.required_files.map((file) => (
                <li key={file.name} className="flex items-center gap-2">
                  <span>{file.name}</span> <OriginTag origin={file.origin} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

/** Ficha da demanda (§13, tela 2): estado, score, campos com origem e triagem. */
export function DemandSheet({ view, config }: { view: RequestView; config: AppConfig }) {
  const demand = view.demand;
  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-semibold">Ficha da demanda</h1>
        <p className="text-sm text-slate-600">
          {demand.requester} · {demand.department}
        </p>
      </header>
      <Section title="Estado">
        <Stepper view={view} />
      </Section>
      <Section title="Briefing Score">
        <Score view={view} />
      </Section>
      <Section title="Campos">
        <Fields view={view} />
      </Section>
      <Triage view={view} config={config} />
    </div>
  );
}
