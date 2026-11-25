// Aceite da T19: caso 06 (§17) de ponta a ponta na UI, com as respostas reais da API gravadas.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AuditLog } from "@/components/AuditLog";
import { DemandWorkspace } from "@/components/DemandWorkspace";
import { NewRequest } from "@/components/NewRequest";
import { TaskBoard } from "@/components/TaskBoard";
import type { ChatMessage, RequestView, Task } from "@/lib/types";
import { fakeApi } from "./fakeApi";
import afterResolve from "./fixtures/case06-after-resolve.json";
import messages from "./fixtures/case06-messages.json";
import second from "./fixtures/case06-second.json";
import {
  approvedView,
  auditLog,
  finalView,
  firstView,
  jsonResponse,
  resolvedTask,
  taskList,
} from "./helpers";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const CASE_06 = [
  "Preciso de uma arte da Krona para amanhã.",
  "Construjá",
  "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. " +
    "Ainda aguardando aprovação de preço por Compras.",
];

describe("caso 06 na UI (T19)", () => {
  it("pedido → respostas → aprovação → tarefa bloqueada → dependência resolvida → registro", async () => {
    const id = firstView().demand.request_id;
    const history = messages as ChatMessage[];
    let shown = 0; // mensagens já "gravadas" no backend simulado
    const state = { view: firstView(), tasks: [] as Task[] };
    const step = (view: RequestView, count: number) => {
      state.view = view;
      shown = count;
      return jsonResponse(view);
    };
    const api = fakeApi({
      routes: {
        "POST /requests": () => {
          shown = 2;
          return jsonResponse(firstView(), 201);
        },
        [`GET /requests/${id}`]: () => jsonResponse(state.view),
        [`GET /requests/${id}/messages`]: () => jsonResponse(history.slice(0, shown)),
        [`POST /requests/${id}/answers`]: (call) =>
          (call.body as { message: string }).message === CASE_06[1]
            ? step(second as RequestView, 4)
            : step(finalView(), 5),
        [`POST /requests/${id}/approve`]: () => {
          state.tasks = taskList();
          return step(approvedView(), 5);
        },
        "GET /tasks": () => jsonResponse(state.tasks),
        "POST /tasks/1/dependencies/0/resolve": () => {
          state.tasks = [resolvedTask()];
          state.view = afterResolve as RequestView;
          return jsonResponse(resolvedTask());
        },
        "GET /audit": () => jsonResponse(auditLog().sort((a, b) => b.id - a.id)),
      },
    });
    const user = userEvent.setup();

    // Tela 1: nova demanda.
    const created = render(<NewRequest />);
    await user.type(screen.getByLabelText("Seu nome"), "Ana");
    await user.type(screen.getByLabelText("Departamento"), "Comercial");
    await user.type(screen.getByLabelText("O que você precisa?"), CASE_06[0]);
    await user.click(screen.getByRole("button", { name: "Enviar pedido" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith(`/demandas/${id}`));
    created.unmount();

    // Telas 1 e 2: chat e ficha; marca pelo chip, depois o restante pelo campo de texto.
    const workspace = render(<DemandWorkspace requestId={id} />);
    await user.click(await screen.findByRole("button", { name: "Construjá" }));
    const chat = within(screen.getByRole("list", { name: "Conversa" }));
    await vi.waitFor(() => expect(chat.getAllByRole("listitem")).toHaveLength(4));
    await user.type(screen.getByLabelText("Sua mensagem"), CASE_06[2]);
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    // Tela 3: Approval Gate com 100%, Alta e Designer A.
    const gate = within(await screen.findByRole("region", { name: "Approval Gate" }));
    expect(gate.getByText("100%")).toBeInTheDocument();
    expect(gate.getByText("Alta")).toBeInTheDocument();
    expect(gate.getByText("Designer A")).toBeInTheDocument();
    expect(screen.getByText("Aprovação de preço")).toBeInTheDocument();
    await user.click(gate.getByRole("button", { name: "Aprovar e criar" }));
    expect(await screen.findByText(/Tarefa criada: MKT-1/)).toBeInTheDocument();
    workspace.unmount();

    // Tela 4: a tarefa nasce bloqueada pela dependência de Compras.
    const board = render(<TaskBoard />);
    const row = await screen.findByRole("row", { name: /Arte \| Promoção Krona \| Construjá/ });
    expect(within(row).getByText("Bloqueada")).toBeInTheDocument();
    expect(within(row).getByText("Designer A")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: /Arte \| Promoção Krona/ }));
    const detail = within(await screen.findByRole("region", { name: "Detalhe da tarefa" }));
    const dependency = within(detail.getByRole("listitem", { name: /Aprovação de preço/ }));
    expect(dependency.getByText("Compras")).toBeInTheDocument();
    await user.click(dependency.getByRole("button", { name: "Resolver" }));
    expect(await within(row).findByText("Aberta")).toBeInTheDocument();
    board.unmount();

    // Tela 5: o registro tem a aprovação, a criação e a resolução.
    render(<AuditLog />);
    const table = within(await screen.findByRole("table", { name: "Registro" }));
    const actions = table.getAllByTestId("audit-action").map((cell) => cell.textContent);
    expect(actions[0]).toBe("dependency_resolved");
    expect(actions).toEqual(expect.arrayContaining(["approved", "task_created"]));

    // Nada foi criado sem o clique de aprovação (§14).
    const writes = api.writes().map((c) => `${c.method} ${c.path}`);
    expect(writes).toEqual([
      "POST /requests",
      `POST /requests/${id}/answers`,
      `POST /requests/${id}/answers`,
      `POST /requests/${id}/approve`,
      "POST /tasks/1/dependencies/0/resolve",
    ]);
  });
});
