import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DemandWorkspace } from "@/components/DemandWorkspace";
import type { RequestView } from "@/lib/types";
import { fakeApi } from "./fakeApi";
import {
  approvedView,
  dupConflict,
  dupPendingView,
  finalView,
  firstView,
  jsonResponse,
} from "./helpers";

function renderGate(view: RequestView, routes = {}) {
  const api = fakeApi({ view, routes });
  render(<DemandWorkspace requestId={view.demand.request_id} />);
  return api;
}

const gate = () => screen.findByRole("region", { name: "Approval Gate" });

describe("Approval Gate (§13, tela 3)", () => {
  it("mostra título, responsável, prioridade, prazo e score", async () => {
    renderGate(finalView());

    const region = within(await gate());
    expect(region.getByText("Arte | Promoção Krona | Construjá")).toBeInTheDocument();
    expect(region.getByText("Designer A")).toBeInTheDocument();
    expect(region.getByText("Alta")).toBeInTheDocument();
    expect(region.getByText("20/10/2026")).toBeInTheDocument();
    expect(region.getByText("100%")).toBeInTheDocument();
    for (const name of ["Aprovar e criar", "Editar", "Cancelar"]) {
      expect(region.getByRole("button", { name })).toBeEnabled();
    }
  });

  it("não aparece antes de a demanda chegar à aprovação", async () => {
    renderGate(firstView());

    await screen.findByRole("meter", { name: "Briefing Score" });
    expect(screen.queryByRole("region", { name: "Approval Gate" })).not.toBeInTheDocument();
  });

  it("Aprovar e criar chama approve sem force_new e mostra a tarefa criada", async () => {
    const view = finalView();
    const api = renderGate(view, {
      [`POST /requests/${view.demand.request_id}/approve`]: () => jsonResponse(approvedView()),
    });
    const user = userEvent.setup();

    await user.click(within(await gate()).getByRole("button", { name: "Aprovar e criar" }));

    expect(await screen.findByText(/Tarefa criada: MKT-1/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver no quadro de tarefas" })).toHaveAttribute(
      "href",
      "/tarefas",
    );
    expect(api.writes()).toEqual([
      expect.objectContaining({ method: "POST", body: { force_new: false } }),
    ]);
    expect(screen.queryByRole("region", { name: "Approval Gate" })).not.toBeInTheDocument();
  });

  it("Editar envia só os campos alterados com PATCH e atualiza a ficha", async () => {
    const view = finalView();
    const edited = finalView();
    edited.demand.priority = "Crítica";
    edited.demand.priority_locked = true;
    edited.demand.field_origin.priority = "manager";
    const api = renderGate(view, {
      [`PATCH /requests/${view.demand.request_id}`]: () => jsonResponse(edited),
    });
    const user = userEvent.setup();

    await user.click(within(await gate()).getByRole("button", { name: "Editar" }));
    await user.selectOptions(screen.getByLabelText("Prioridade"), "Crítica");
    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));

    expect(api.writes()).toEqual([
      expect.objectContaining({ method: "PATCH", body: { priority: "Crítica" } }),
    ]);
    const region = within(await gate());
    expect(await region.findByText("Crítica")).toBeInTheDocument();
    expect(region.getByText("Gestor")).toBeInTheDocument();
  });

  it("Editar: responsável e prazo; 'Automático' destrava o que o gestor travou", async () => {
    const view = finalView();
    view.demand.priority_locked = true;
    view.demand.field_origin.priority = "manager";
    const api = renderGate(view, {
      [`PATCH /requests/${view.demand.request_id}`]: () => jsonResponse(finalView()),
    });
    const user = userEvent.setup();

    await user.click(within(await gate()).getByRole("button", { name: "Editar" }));
    expect(screen.getByLabelText("Prioridade")).toHaveValue("Alta");
    expect(screen.getByLabelText("Responsável")).toHaveValue("");
    await user.selectOptions(screen.getByLabelText("Prioridade"), "");
    await user.selectOptions(screen.getByLabelText("Responsável"), "designer-b");
    fireEvent.change(screen.getByLabelText("Prazo"), { target: { value: "2026-10-23" } });
    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));

    expect(api.writes()[0].body).toEqual({
      priority: null,
      assigned_to: "designer-b",
      deadline: "2026-10-23",
    });
  });

  it("Editar sem mudança não chama a API; Descartar fecha o formulário", async () => {
    const api = renderGate(finalView());
    const user = userEvent.setup();

    await user.click(within(await gate()).getByRole("button", { name: "Editar" }));
    expect(screen.getByRole("button", { name: "Salvar alterações" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Descartar" }));

    expect(screen.queryByLabelText("Prioridade")).not.toBeInTheDocument();
    expect(api.writes()).toEqual([]);
  });

  it("Cancelar pede confirmação antes de cancelar a demanda", async () => {
    const view = finalView();
    const cancelled = finalView();
    cancelled.demand.status = "CANCELLED";
    cancelled.next_action = "CANCELLED";
    const api = renderGate(view, {
      [`POST /requests/${view.demand.request_id}/cancel`]: () => jsonResponse(cancelled),
    });
    const user = userEvent.setup();

    await user.click(within(await gate()).getByRole("button", { name: "Cancelar" }));
    expect(api.writes()).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Confirmar cancelamento" }));

    expect(await screen.findByText(/Demanda fora do fluxo/)).toHaveTextContent("Cancelada");
    expect(api.writes()).toEqual([expect.objectContaining({ method: "POST", body: undefined })]);
  });

  it("duplicidade da triagem vira alerta; Usar existente vincula à tarefa", async () => {
    const view = dupPendingView();
    const linked = dupPendingView();
    linked.demand.status = "CANCELLED";
    linked.demand.external_task_id = "MKT-1";
    const api = renderGate(view, {
      [`POST /requests/${view.demand.request_id}/link-existing`]: () => jsonResponse(linked),
    });
    const user = userEvent.setup();

    const alert = within(await screen.findByRole("alert", { name: "Possível duplicidade" }));
    expect(alert.getByText(/Arte \| Promoção Krona \| Construjá/)).toBeInTheDocument();
    expect(alert.getByText(/#1/)).toBeInTheDocument();
    await user.click(alert.getByRole("button", { name: "Usar existente" }));

    expect(api.writes()).toEqual([expect.objectContaining({ body: { task_id: 1 } })]);
    expect(await screen.findByText(/Vinculada à tarefa existente MKT-1/)).toBeInTheDocument();
  });

  it("Criar nova aprova com force_new", async () => {
    const view = dupPendingView();
    const api = renderGate(view, {
      [`POST /requests/${view.demand.request_id}/approve`]: () => jsonResponse(approvedView()),
    });
    const user = userEvent.setup();

    const alert = within(await screen.findByRole("alert", { name: "Possível duplicidade" }));
    await user.click(alert.getByRole("button", { name: "Criar nova" }));

    expect(api.writes()).toEqual([expect.objectContaining({ body: { force_new: true } })]);
  });

  it("409 de duplicidade na aprovação abre o alerta com a tarefa existente", async () => {
    const view = finalView();
    renderGate(view, {
      [`POST /requests/${view.demand.request_id}/approve`]: () => jsonResponse(dupConflict(), 409),
    });
    const user = userEvent.setup();

    expect(screen.queryByRole("alert", { name: "Possível duplicidade" })).not.toBeInTheDocument();
    await user.click(within(await gate()).getByRole("button", { name: "Aprovar e criar" }));

    const alert = await screen.findByRole("alert", { name: "Possível duplicidade" });
    expect(alert).toHaveTextContent("#1");
    expect(within(alert).getByRole("button", { name: "Criar nova" })).toBeEnabled();
  });

  it("falha ao criar a tarefa (502) mostra o erro; em APPROVED dá para tentar de novo", async () => {
    const view = finalView();
    view.demand.status = "APPROVED";
    const api = renderGate(view, {
      [`POST /requests/${view.demand.request_id}/approve`]: () =>
        jsonResponse({ detail: "Asana fora do ar" }, 502),
    });
    const user = userEvent.setup();

    const region = within(await gate());
    expect(region.getByText(/criação da tarefa falhou/)).toBeInTheDocument();
    expect(region.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    await user.click(region.getByRole("button", { name: "Tentar criar de novo" }));

    expect(await region.findByText("Asana fora do ar")).toBeInTheDocument();
    expect(api.writes()).toEqual([expect.objectContaining({ body: { force_new: false } })]);
  });
});
