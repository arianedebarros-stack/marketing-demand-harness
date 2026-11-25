// Cliente da API do harness (SPEC §9). Toda decisão fica no backend; aqui só HTTP.

import type {
  AppConfig,
  AuditEntry,
  ChatMessage,
  DemandPatch,
  DuplicateConflict,
  RequestView,
  Task,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Canal de entrada das demandas criadas pela tela "Nova demanda". */
export const CHAT_CHANNEL = "chat";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detailMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => (item as { msg?: unknown })?.msg).filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return `Erro ${status} na API`;
}

async function request<T>(path: string, init?: { method: string; body?: unknown }): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: init?.method ?? "GET",
      headers: init?.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new ApiError(0, `Não foi possível falar com a API em ${API_URL}. Ela está rodando?`);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, detailMessage(body, response.status), body);
  return body as T;
}

export interface NewRequestInput {
  requesterName: string;
  department: string;
  message: string;
}

export function createRequest(input: NewRequestInput): Promise<RequestView> {
  return request("/requests", {
    method: "POST",
    body: {
      requester_name: input.requesterName,
      department: input.department,
      channel: CHAT_CHANNEL,
      message: input.message,
    },
  });
}

export function getRequest(id: string): Promise<RequestView> {
  return request(`/requests/${id}`);
}

export function getMessages(id: string): Promise<ChatMessage[]> {
  return request(`/requests/${id}/messages`);
}

export function sendAnswer(id: string, message: string): Promise<RequestView> {
  return request(`/requests/${id}/answers`, { method: "POST", body: { message } });
}

export function confirmType(id: string, taskType: string): Promise<RequestView> {
  return request(`/requests/${id}/confirm-type`, { method: "POST", body: { task_type: taskType } });
}

export function getConfig(): Promise<AppConfig> {
  return request("/config");
}

// --- Approval Gate (§13, tela 3) ---------------------------------------------------------------

export function approve(id: string, forceNew = false): Promise<RequestView> {
  return request(`/requests/${id}/approve`, { method: "POST", body: { force_new: forceNew } });
}

export function linkExisting(id: string, taskId: number): Promise<RequestView> {
  return request(`/requests/${id}/link-existing`, { method: "POST", body: { task_id: taskId } });
}

export function cancelRequest(id: string): Promise<RequestView> {
  return request(`/requests/${id}/cancel`, { method: "POST" });
}

export function patchRequest(id: string, patch: DemandPatch): Promise<RequestView> {
  return request(`/requests/${id}`, { method: "PATCH", body: patch });
}

/** O 409 de `approve` com a tarefa parecida, quando for esse o erro. */
export function duplicateConflict(exc: unknown): DuplicateConflict | null {
  if (!(exc instanceof ApiError) || exc.status !== 409) return null;
  const body = exc.body as Partial<DuplicateConflict> | null;
  return body?.duplicate && body.task ? (body as DuplicateConflict) : null;
}

// --- Quadro de tarefas (§13, tela 4) -----------------------------------------------------------

export function listTasks(): Promise<Task[]> {
  return request("/tasks");
}

export function resolveDependency(taskId: number, index: number): Promise<Task> {
  return request(`/tasks/${taskId}/dependencies/${index}/resolve`, { method: "POST" });
}

export function completeTask(taskId: number): Promise<Task> {
  return request(`/tasks/${taskId}/complete`, { method: "POST" });
}

// --- Registro (§13, tela 5; D40) -------------------------------------------------------------

export interface AuditQuery {
  requestId?: string;
  before?: number;
  limit?: number;
}

export function listAudit(query: AuditQuery = {}): Promise<AuditEntry[]> {
  const params = new URLSearchParams();
  if (query.requestId) params.set("request_id", query.requestId);
  if (query.before !== undefined) params.set("before", String(query.before));
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  const search = params.toString();
  return request(`/audit${search ? `?${search}` : ""}`);
}
