import type { AppConfig, RequestView } from "@/lib/types";
import config from "./fixtures/config.json";
import final from "./fixtures/case06-final.json";
import first from "./fixtures/case06-first.json";

/** Cópias novas a cada chamada: os testes podem alterar à vontade. */
export const firstView = (): RequestView => structuredClone(first) as RequestView;
export const finalView = (): RequestView => structuredClone(final) as RequestView;
export const appConfig = (): AppConfig => structuredClone(config) as AppConfig;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
