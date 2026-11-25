import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AUDIT_PAGE_SIZE, AuditLog } from "@/components/AuditLog";
import type { AuditEntry } from "@/lib/types";
import { fakeApi } from "./fakeApi";
import { auditLog, jsonResponse } from "./helpers";

/** O GET /audit devolve em ordem decrescente (D40). */
const newestFirst = (): AuditEntry[] => auditLog().sort((a, b) => b.id - a.id);

describe("Registro (§13, tela 5)", () => {
  it("mostra o audit log em ordem decrescente, com ator e link para a demanda", async () => {
    const entries = newestFirst();
    const api = fakeApi({ audit: entries });
    render(<AuditLog />);

    const table = within(await screen.findByRole("table", { name: "Registro" }));
    const ids = table.getAllByTestId("audit-id").map((cell) => Number(cell.textContent));
    expect(ids).toEqual(entries.map((e) => e.id));
    expect(table.getAllByText("Harness").length).toBeGreaterThan(0);
    expect(table.getAllByText("Gestor").length).toBeGreaterThan(0);
    const [link] = table.getAllByRole("link", { name: /Demanda/ });
    expect(link).toHaveAttribute("href", `/demandas/${entries[0].request_id}`);
    expect(api.calls[0].path).toBe(`/audit?limit=${AUDIT_PAGE_SIZE}`);
  });

  it("os valores da linha aparecem em JSON", async () => {
    fakeApi({ audit: newestFirst() });
    render(<AuditLog />);

    const row = (await screen.findAllByRole("row", { name: /task_created/ }))[0];
    expect(row).toHaveTextContent('"external_task_id":"MKT-1"');
  });

  it("filtra por demanda e oferece ver tudo", async () => {
    const entries = newestFirst();
    const requestId = entries[0].request_id as string;
    const api = fakeApi({ audit: entries });
    render(<AuditLog requestId={requestId} />);

    await screen.findByRole("table", { name: "Registro" });
    expect(api.calls[0].path).toBe(`/audit?request_id=${requestId}&limit=${AUDIT_PAGE_SIZE}`);
    expect(screen.getByRole("link", { name: "Ver o registro completo" })).toHaveAttribute(
      "href",
      "/registro",
    );
  });

  it("Carregar mais pede a página seguinte pelo cursor", async () => {
    const entries = newestFirst();
    const page = Array.from({ length: AUDIT_PAGE_SIZE }, (_, i) => ({
      ...entries[0],
      id: 10_000 - i,
    }));
    const api = fakeApi({
      routes: {
        "GET /audit": (call) =>
          jsonResponse(call.path.includes("before=") ? entries.slice(0, 2) : page),
      },
    });
    const user = userEvent.setup();
    render(<AuditLog />);

    await user.click(await screen.findByRole("button", { name: "Carregar mais" }));

    expect(api.calls.at(-1)?.path).toBe(`/audit?before=${page.at(-1)?.id}&limit=${AUDIT_PAGE_SIZE}`);
    const table = within(screen.getByRole("table", { name: "Registro" }));
    expect(await table.findAllByTestId("audit-id")).toHaveLength(AUDIT_PAGE_SIZE + 2);
    expect(screen.queryByRole("button", { name: "Carregar mais" })).not.toBeInTheDocument();
  });

  it("sem registros mostra um aviso", async () => {
    fakeApi({ audit: [] });
    render(<AuditLog />);

    expect(await screen.findByText("Nenhum registro.")).toBeInTheDocument();
  });

  it("erro da API aparece", async () => {
    fakeApi({ routes: { "GET /audit": () => jsonResponse({ detail: "banco fora do ar" }, 500) } });
    render(<AuditLog />);

    expect(await screen.findByRole("alert")).toHaveTextContent("banco fora do ar");
  });
});
