// Cliente da API do harness (SPEC §9). Toda decisão fica no backend; aqui só HTTP.

import type { AppConfig, ChatMessage, RequestView } from "./types";

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
