import type { AppConfig, AuditEntry, DuplicateConflict, RequestView, Task } from "@/lib/types";
import approved from "./fixtures/case06-approved.json";
import audit from "./fixtures/case06-audit.json";
import resolved from "./fixtures/case06-task-resolved.json";
import tasks from "./fixtures/case06-tasks.json";
import dup409 from "./fixtures/dup-409.json";
import dupPending from "./fixtures/dup-pending.json";
import config from "./fixtures/config.json";
import final from "./fixtures/case06-final.json";
import first from "./fixtures/case06-first.json";

/** Cópias novas a cada chamada: os testes podem alterar à vontade. */
export const firstView = (): RequestView => structuredClone(first) as RequestView;
export const finalView = (): RequestView => structuredClone(final) as RequestView;
export const approvedView = (): RequestView => structuredClone(approved) as RequestView;
export const dupPendingView = (): RequestView => structuredClone(dupPending) as RequestView;
export const dupConflict = (): DuplicateConflict => structuredClone(dup409) as DuplicateConflict;
export const taskList = (): Task[] => structuredClone(tasks) as Task[];
export const resolvedTask = (): Task => structuredClone(resolved) as Task;
export const auditLog = (): AuditEntry[] => structuredClone(audit) as AuditEntry[];
export const appConfig = (): AppConfig => structuredClone(config) as AppConfig;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
