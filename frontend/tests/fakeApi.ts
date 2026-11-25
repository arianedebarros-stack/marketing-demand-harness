// API simulada para os testes de tela: responde com as respostas reais gravadas em fixtures
// (caso 06 com o FakeLLMClient) e guarda as chamadas para os testes conferirem.

import { vi } from "vitest";
import type { AuditEntry, ChatMessage, RequestView, Task } from "@/lib/types";
import { appConfig, jsonResponse } from "./helpers";

export interface Call {
  method: string;
  path: string;
  body: unknown;
}

type Handler = (call: Call) => Response | Promise<Response>;

export interface FakeApiState {
  view?: RequestView;
  messages?: ChatMessage[];
  tasks?: Task[];
  audit?: AuditEntry[];
  /** Respostas por "MÉTODO /caminho" (sem a origem); têm prioridade sobre as rotas padrão. */
  routes?: Record<string, Handler>;
}

export function fakeApi(state: FakeApiState = {}) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const parsed = new URL(url);
    const call: Call = {
      method: init?.method ?? "GET",
      path: parsed.pathname + parsed.search,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const custom = state.routes?.[`${call.method} ${parsed.pathname}`];
    if (custom) return custom(call);
    if (parsed.pathname === "/config") return jsonResponse(appConfig());
    if (parsed.pathname === "/tasks" && call.method === "GET") return jsonResponse(state.tasks ?? []);
    if (parsed.pathname === "/audit") return jsonResponse(state.audit ?? []);
    if (parsed.pathname.endsWith("/messages")) return jsonResponse(state.messages ?? []);
    if (state.view && parsed.pathname === `/requests/${state.view.demand.request_id}`) {
      return jsonResponse(state.view);
    }
    return jsonResponse({ detail: `rota não simulada: ${call.method} ${call.path}` }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    fetchMock,
    state,
    /** Chamadas que mudam algo (tudo menos GET). */
    writes: () => calls.filter((c) => c.method !== "GET"),
  };
}
