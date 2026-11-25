// Apresentação da demanda na UI. Nada aqui decide estado, score, prioridade ou responsável:
// tudo vem pronto da API (faltantes em `missing_information`, triagem no audit).

import type {
  AppConfig,
  AuditEntry,
  Demand,
  DemandPatch,
  FieldOrigin,
  PriorityLevel,
  RequestStatus,
  RequestView,
  Task,
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

// --- Approval Gate (§13, tela 3) -------------------------------------------------------------

/** Estados em que o gate aparece: aguardando aprovação, ou aprovada com a criação falhando (D04). */
export function showsApprovalGate(status: RequestStatus): boolean {
  return status === "PENDING_APPROVAL" || status === "APPROVED";
}

/** Níveis de prioridade na ordem de `priorities.json` (`bands`). */
export function priorityLevels(config: AppConfig): PriorityLevel[] {
  return config.priorities.bands.map((band) => band.level);
}

export const DUPLICATE_CRITERIA_LABELS: Record<string, string> = {
  same_brand_type_supplier: "mesma marca, tipo e fornecedor",
  same_brand_type_campaign: "mesma marca, tipo e campanha",
  similar_title: "título parecido",
};

/** Valores do formulário "Editar": vazio = automático (sem trava do gestor). */
export interface GateForm {
  priority: string;
  assigned_to: string;
  deadline: string;
}

export function gateForm(demand: Demand): GateForm {
  return {
    priority: demand.priority_locked ? (demand.priority ?? "") : "",
    assigned_to: demand.assignment_locked ? (demand.assigned_to ?? "") : "",
    deadline: typeof demand.deadline === "string" ? demand.deadline : "",
  };
}

/** Só os campos alterados; vazio vira `null` (destrava ou limpa, D36). */
export function gatePatch(before: GateForm, after: GateForm): DemandPatch {
  const patch: DemandPatch = {};
  if (after.priority !== before.priority) {
    patch.priority = (after.priority || null) as PriorityLevel | null;
  }
  if (after.assigned_to !== before.assigned_to) patch.assigned_to = after.assigned_to || null;
  if (after.deadline !== before.deadline) patch.deadline = after.deadline || null;
  return patch;
}

// --- Quadro de tarefas (§13, tela 4) -------------------------------------------------------

export type TaskStatusLabel = "Aberta" | "Bloqueada" | "Concluída";

/** Bloqueada é a flag `blocked` de uma tarefa aberta (D03). */
export function taskStatus(task: Task): TaskStatusLabel {
  if (task.status === "Concluída") return "Concluída";
  return task.blocked ? "Bloqueada" : "Aberta";
}

// --- Registro (§13, tela 5) ------------------------------------------------------------------

export const ACTOR_LABELS: Record<AuditEntry["actor"], string> = {
  llm: "IA",
  harness: "Harness",
  user: "Usuário",
  manager: "Gestor",
};

/** Mais recente primeiro (pelo id, que segue a ordem de gravação). */
export function newestFirst(entries: AuditEntry[]): AuditEntry[] {
  return [...entries].sort((a, b) => b.id - a.id);
}

const dateTime = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" });

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateTime.format(date);
}

/** Valor do audit em JSON compacto; vazio quando não há valor. */
export function auditValue(value: unknown): string {
  return value === null || value === undefined ? "" : JSON.stringify(value);
}
