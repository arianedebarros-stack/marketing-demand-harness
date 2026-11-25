import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TaskBoard } from "@/components/TaskBoard";
import { taskStatus } from "@/lib/demand";
import type { Task } from "@/lib/types";
import { fakeApi } from "./fakeApi";
import { approvedView, jsonResponse, resolvedTask, taskList } from "./helpers";

function boardApi(tasks: Task[] = taskList(), routes = {}) {
  return fakeApi({ tasks, view: approvedView(), routes });
}

describe("status da tarefa (§13, tela 4)", () => {
  it("Concluída vence; aberta com dependência pendente é Bloqueada (D03)", () => {
    const [task] = taskList();
    expect(taskStatus(task)).toBe("Bloqueada");
    expect(taskStatus({ ...task, blocked: false })).toBe("Aberta");
    expect(taskStatus({ ...task, status: "Concluída" })).toBe("Concluída");
  });
});

describe("Quadro de tarefas (§13, tela 4)", () => {
  it("lista as tarefas com status, responsável, prioridade e prazo", async () => {
    boardApi();
    render(<TaskBoard />);

    const row = await screen.findByRole("row", { name: /Arte \| Promoção Krona \| Construjá/ });
    const cells = within(row);
    expect(cells.getByText("MKT-1")).toBeInTheDocument();
    expect(cells.getByText("Bloqueada")).toBeInTheDocument();
    expect(cells.getByText("Designer A")).toBeInTheDocument();
    expect(cells.getByText("Alta")).toBeInTheDocument();
    expect(cells.getByText("20/10/2026")).toBeInTheDocument();
  });

  it("sem tarefas mostra um aviso", async () => {
    boardApi([]);
    render(<TaskBoard />);

    expect(await screen.findByText("Nenhuma tarefa criada ainda.")).toBeInTheDocument();
  });

  it("o detalhe mostra o briefing e o histórico da demanda, mais recente primeiro", async () => {
    boardApi();
    const user = userEvent.setup();
    render(<TaskBoard />);

    await user.click(await screen.findByRole("button", { name: /Arte \| Promoção Krona/ }));

    const detail = within(await screen.findByRole("region", { name: "Detalhe da tarefa" }));
    expect(detail.getByText(/DEPENDÊNCIAS: Aprovação de preço \(Compras, Pendente\)/)).toBeInTheDocument();
    const history = within(await detail.findByRole("table", { name: "Histórico" }));
    const actions = history.getAllByTestId("audit-action").map((cell) => cell.textContent);
    expect(actions[0]).toBe("status_transition");
    expect(actions).toContain("task_created");
    expect(actions.at(-1)).toBe("message_received");
    expect(detail.getByRole("link", { name: "Abrir a demanda" })).toHaveAttribute(
      "href",
      `/demandas/${taskList()[0].request_id}`,
    );
  });

  it("abre já com a tarefa escolhida pela URL", async () => {
    boardApi();
    render(<TaskBoard initialTaskId={1} />);

    expect(await screen.findByRole("region", { name: "Detalhe da tarefa" })).toHaveTextContent(
      "MKT-1",
    );
  });

  it("resolver a dependência desbloqueia a tarefa", async () => {
    const api = boardApi(taskList(), {
      "POST /tasks/1/dependencies/0/resolve": () => jsonResponse(resolvedTask()),
    });
    const user = userEvent.setup();
    render(<TaskBoard initialTaskId={1} />);

    const detail = within(await screen.findByRole("region", { name: "Detalhe da tarefa" }));
    const dependency = within(detail.getByRole("listitem", { name: /Aprovação de preço/ }));
    expect(dependency.getByText("Compras")).toBeInTheDocument();
    await user.click(dependency.getByRole("button", { name: "Resolver" }));

    expect(await dependency.findByText("Resolvida")).toBeInTheDocument();
    expect(dependency.queryByRole("button", { name: "Resolver" })).not.toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Arte \| Promoção Krona/ });
    expect(within(row).getByText("Aberta")).toBeInTheDocument();
    expect(api.writes()).toEqual([
      expect.objectContaining({ method: "POST", path: "/tasks/1/dependencies/0/resolve" }),
    ]);
  });

  it("concluir a tarefa muda o status para Concluída", async () => {
    const done = { ...resolvedTask(), status: "Concluída" as const };
    boardApi([resolvedTask()], { "POST /tasks/1/complete": () => jsonResponse(done) });
    const user = userEvent.setup();
    render(<TaskBoard initialTaskId={1} />);

    const detail = within(await screen.findByRole("region", { name: "Detalhe da tarefa" }));
    await user.click(detail.getByRole("button", { name: "Concluir tarefa" }));

    const row = await screen.findByRole("row", { name: /Arte \| Promoção Krona/ });
    expect(await within(row).findByText("Concluída")).toBeInTheDocument();
    expect(detail.queryByRole("button", { name: "Concluir tarefa" })).not.toBeInTheDocument();
  });

  it("erro da API aparece no detalhe", async () => {
    boardApi(taskList(), {
      "POST /tasks/1/complete": () => jsonResponse({ detail: "a tarefa 1 já está concluída" }, 409),
    });
    const user = userEvent.setup();
    render(<TaskBoard initialTaskId={1} />);

    const detail = within(await screen.findByRole("region", { name: "Detalhe da tarefa" }));
    await user.click(detail.getByRole("button", { name: "Concluir tarefa" }));

    expect(await detail.findByRole("alert")).toHaveTextContent("já está concluída");
  });
});
