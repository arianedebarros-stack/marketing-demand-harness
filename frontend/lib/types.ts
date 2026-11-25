// Tipos das respostas da API (SPEC §6 e §9; backend/app/schemas). Só a forma: nenhuma regra.

export type RequestStatus =
  | "RECEIVED"
  | "PARSED"
  | "VALIDATING"
  | "NEEDS_INFORMATION"
  | "READY_FOR_TRIAGE"
  | "TRIAGED"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "TASK_CREATED"
  | "CANCELLED"
  | "REJECTED"
  | "ERROR";

export type FieldOrigin = "message" | "llm" | "rule" | "harness" | "manager" | "requester";
export type PriorityLevel = "Crítica" | "Alta" | "Normal" | "Baixa";
export type NextAction =
  | "REQUEST_INFORMATION"
  | "CONFIRM_TYPE"
  | "AWAIT_APPROVAL"
  | "DONE"
  | "CANCELLED";
export type ScoreBand = "Incompleto" | "Parcial" | "Quase pronto" | "Pronto para produção";

export interface Dependency {
  dependency: string;
  owner: string;
  status: "Pendente" | "Resolvida";
}

export interface RequiredFile {
  name: string;
  origin: FieldOrigin;
}

export interface DuplicateCandidate {
  task_id: number;
  title: string;
  criteria: string[];
  jaccard: number;
}

/** Demanda (§6). Os campos de conteúdo são texto ou data ISO; ver `CONTENT_FIELDS`. */
export interface Demand {
  request_id: string;
  requester: string;
  department: string;
  task_type: string | null;
  priority: PriorityLevel | null;
  priority_score: number | null;
  priority_locked: boolean;
  assigned_to: string | null;
  assignment_locked: boolean;
  approver: string | null;
  dependencies: Dependency[];
  required_files: RequiredFile[];
  missing_information: string[];
  is_promotional: boolean;
  published_error: boolean;
  briefing_score: number;
  classification_confidence: number;
  type_confirmed: boolean;
  status: RequestStatus;
  field_origin: Partial<Record<string, FieldOrigin>>;
  external_task_id: string | null;
  duplicate_of: DuplicateCandidate | null;
  [field: string]: unknown;
}

export interface Question {
  fields: string[];
  text: string;
}

export interface AuditEntry {
  id: number;
  request_id: string | null;
  task_id: number | null;
  actor: "llm" | "harness" | "user" | "manager";
  action: string;
  previous_value: unknown;
  new_value: unknown;
  timestamp: string;
}

export interface RequestView {
  demand: Demand;
  next_action: NextAction;
  questions: Question[];
  score_band: ScoreBand;
  audit: AuditEntry[];
}

/** GET /requests/{id}/messages (D39). */
export interface ChatMessage {
  id: number;
  role: "requester" | "assistant";
  text: string;
  created_at: string;
}

export interface TeamMember {
  id: string;
  name: string;
  skills: string[];
  capacity: number;
  open_base: number;
}

/** Parte do GET /config que a UI usa (nomes de marca, tipos, equipe e aprovador). */
export interface AppConfig {
  brands: Record<string, { name: string; [key: string]: unknown }>;
  task_types: {
    approver_default: string;
    types: Record<string, unknown>;
    [key: string]: unknown;
  };
  team: TeamMember[];
  [key: string]: unknown;
}
