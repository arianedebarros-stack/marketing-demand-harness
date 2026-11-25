// Apresentação da demanda na UI. Nada aqui decide estado, score, prioridade ou responsável:
// tudo vem pronto da API (faltantes em `missing_information`, triagem no audit).

import type {
  AppConfig,
  AuditEntry,
  Demand,
  FieldOrigin,
  PriorityLevel,
  RequestStatus,
  RequestView,
} from "./types";

// --- Stepper -------------------------------------------------------------------------------

export const STEPS: { label: string; statuses: RequestStatus[] }[] = [
  { label: "Recebida", statuses: ["RECEIVED", "PARSED"] },
  { label: "Validação", statuses: ["VALIDATING", "NEEDS_INFORMATION"] },
  { label: "Triagem", statuses: ["READY_FOR_TRIAGE", "TRIAGED"] },
  { label: "Aprovação", statuses: ["PENDING_APPROVAL", "APPROVED"] },
  { label: "Tarefa criada", statuses: ["TASK_CREATED"] },
];

/** Índice da etapa atual; `null` para estados fora do fluxo (cancelada, rejeitada, erro). */
export function currentStep(status: RequestStatus): number | null {
  const index = STEPS.findIndex((step) => step.statuses.includes(status));
  return index === -1 ? null : index;
}

export const STATUS_LABELS: Record<RequestStatus, string> = {
  RECEIVED: "Recebida",
  PARSED: "Interpretada",
  VALIDATING: "Em validação",
  NEEDS_INFORMATION: "Faltam informações",
  READY_FOR_TRIAGE: "Pronta para triagem",
  TRIAGED: "Triada",
  PENDING_APPROVAL: "Aguardando aprovação",
  APPROVED: "Aprovada",
  TASK_CREATED: "Tarefa criada",
  CANCELLED: "Cancelada",
  REJECTED: "Rejeitada",
  ERROR: "Erro",
};

/** Estados em que o backend aceita nova mensagem do solicitante (§7, D31). */
export function canSendMessage(status: RequestStatus): boolean {
  return status === "NEEDS_INFORMATION" || status === "PENDING_APPROVAL";
}

// --- Campos --------------------------------------------------------------------------------

export const ORIGIN_LABELS: Record<FieldOrigin, string> = {
  message: "Mensagem",
  llm: "IA",
  rule: "Regra",
  harness: "Harness",
  manager: "Gestor",
  requester: "Solicitante",
};

/** Rótulos dos campos de conteúdo (§6), na ordem em que aparecem na ficha. */
export const FIELD_LABELS: Record<string, string> = {
  task_type: "Tipo",
  brand: "Marca",
  company: "Empresa",
  campaign: "Campanha",
  supplier: "Fornecedor",
  objective: "Objetivo",
  audience: "Público",
  message_tone: "Mensagem e tom",
  channel: "Canal",
  format: "Formato",
  dimensions: "Dimensão",
  product: "Produtos",
  price: "Preços",
  validity: "Vigência",
  cta: "CTA",
  deadline: "Prazo",
  duration: "Duração",
  concept: "Conceito",
  location: "Local",
  participants: "Participantes",
  shoot_date: "Data da gravação",
  headline: "Título da peça",
  landing_page: "Landing page",
  link: "Link",
  publish_period: "Período de publicação",
  size: "Tamanho",
  quantity: "Quantidade",
  material: "Material",
  finishing: "Acabamento",
  event_name: "Nome do evento",
  event_date: "Data do evento",
  event_time: "Horário do evento",
  participants_count: "Nº de participantes",
  budget: "Orçamento",
  deliverables: "Entregáveis",
};

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "2026-10-20" → "20/10/2026"; texto livre (ex.: vigência) fica como está. */
export function formatDate(value: string): string {
  const match = ISO_DATE.exec(value);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : value;
}

function displayValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text ? formatDate(text) : null;
}

export interface FieldRow {
  field: string;
  label: string;
  value: string | null;
  origin: FieldOrigin | null;
  missing: boolean;
}

/** Campos preenchidos (com a origem) e faltantes informados pela API, sem repetição. */
export function fieldRows(demand: Demand): FieldRow[] {
  const missing = new Set(demand.missing_information);
  const known = Object.keys(FIELD_LABELS);
  const extra = demand.missing_information.filter((field) => !known.includes(field));
  return [...known, ...extra].flatMap((field) => {
    const value = displayValue(demand[field]);
    if (value === null && !missing.has(field)) return [];
    return [
      {
        field,
        label: FIELD_LABELS[field] ?? field,
        value,
        origin: demand.field_origin[field] ?? null,
        missing: missing.has(field),
      },
    ];
  });
}

// --- Triagem (lida do audit, gravada pelos engines) ----------------------------------------

function latest(audit: AuditEntry[], actions: string[]): AuditEntry | null {
  return audit
    .filter((entry) => actions.includes(entry.action))
    .reduce<AuditEntry | null>((last, entry) => (!last || entry.id > last.id ? entry : last), null);
}

export interface PriorityInfo {
  level: PriorityLevel | null;
  score: number | null;
  reasons: string[];
}

export function latestPriority(audit: AuditEntry[]): PriorityInfo | null {
  const entry = latest(audit, ["priority_calculated", "priority_locked"]);
  if (!entry) return null;
  const value = (entry.new_value ?? {}) as Partial<PriorityInfo>;
  return { level: value.level ?? null, score: value.score ?? null, reasons: value.reasons ?? [] };
}

export interface MemberLoad {
  employee_id: string;
  name: string;
  load: number;
  open_tasks: number;
  high_priority_open: number;
}

export interface AssignmentInfo {
  employee_id: string | null;
  name: string;
  reason: string;
  loads: MemberLoad[];
}

export function latestAssignment(audit: AuditEntry[]): AssignmentInfo | null {
  const entry = latest(audit, ["assignment_calculated", "assignment_locked"]);
  if (!entry) return null;
  const value = (entry.new_value ?? {}) as Partial<AssignmentInfo>;
  return {
    employee_id: value.employee_id ?? null,
    name: value.name ?? "",
    reason: value.reason ?? "",
    loads: value.loads ?? [],
  };
}

export function memberName(id: string, config: AppConfig): string {
  return config.team.find((member) => member.id === id)?.name ?? id;
}

const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 0 });

export const formatNumber = (value: number): string => decimal.format(value);
export const formatPercent = (fraction: number): string => percent.format(fraction);

// --- Chips do chat (§13) -------------------------------------------------------------------

/** Nomes de marca do config quando a pergunta da vez inclui a marca. */
export function brandChips(view: RequestView, config: AppConfig): string[] {
  const asksBrand = view.questions.some((question) => question.fields.includes("brand"));
  return asksBrand ? Object.values(config.brands).map((brand) => brand.name) : [];
}

/** Tipos do config quando a API pede a confirmação do tipo. */
export function typeChips(view: RequestView, config: AppConfig): string[] {
  return view.next_action === "CONFIRM_TYPE" ? Object.keys(config.task_types.types) : [];
}
