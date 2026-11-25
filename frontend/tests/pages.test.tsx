import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DemandWorkspace } from "@/components/DemandWorkspace";
import { NewRequest } from "@/components/NewRequest";
import { appConfig, finalView, firstView, jsonResponse } from "./helpers";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

beforeEach(() => push.mockReset());

describe("Nova demanda (§13, tela 1)", () => {
  it("cria a demanda com nome, departamento e mensagem e abre a ficha", async () => {
    const view = firstView();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(view, 201));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<NewRequest />);

    await user.type(screen.getByLabelText("Seu nome"), "Ana");
    await user.type(screen.getByLabelText("Departamento"), "Comercial");
    await user.type(
      screen.getByLabelText("O que você precisa?"),
      "Preciso de uma arte da Krona para amanhã.",
    );
    await user.click(screen.getByRole("button", { name: "Enviar pedido" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/demandas/${view.demand.request_id}`));
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      requester_name: "Ana",
      department: "Comercial",
    });
  });

  it("não envia sem os três campos", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<NewRequest />);

    await user.type(screen.getByLabelText("Seu nome"), "Ana");

    expect(screen.getByRole("button", { name: "Enviar pedido" })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("mostra o erro da API e não navega", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "falha do LLM" }, 502)),
    );
    const user = userEvent.setup();
    render(<NewRequest />);

    await user.type(screen.getByLabelText("Seu nome"), "Ana");
    await user.type(screen.getByLabelText("Departamento"), "Comercial");
    await user.type(screen.getByLabelText("O que você precisa?"), "Uma arte");
    await user.click(screen.getByRole("button", { name: "Enviar pedido" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("falha do LLM");
    expect(push).not.toHaveBeenCalled();
  });
});

describe("Página da demanda: chat + ficha", () => {
  function routeFetch(viewAfterAnswer = finalView()) {
    const first = firstView();
    const id = first.demand.request_id;
    const messages = [
      { id: 1, role: "requester", text: "Preciso de uma arte da Krona para amanhã.", created_at: "" },
      { id: 2, role: "assistant", text: "Para qual marca é a demanda?", created_at: "" },
    ];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/config")) return jsonResponse(appConfig());
      if (url.endsWith(`/requests/${id}/messages`)) return jsonResponse(messages);
      if (url.endsWith(`/requests/${id}/answers`) && init?.method === "POST") {
        messages.push({ id: 3, role: "requester", text: "Construjá", created_at: "" });
        return jsonResponse(viewAfterAnswer);
      }
      if (url.endsWith(`/requests/${id}`)) return jsonResponse(first);
      return jsonResponse({ detail: "rota não simulada" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    return { id, fetchMock };
  }

  it("carrega a demanda, o histórico e o config e mostra chat e ficha", async () => {
    const { id } = routeFetch();
    render(<DemandWorkspace requestId={id} />);

    expect(await screen.findByText("Para qual marca é a demanda?")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Briefing Score" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Construjá" })).toBeInTheDocument();
  });

  it("responder pelo chip atualiza a ficha e o histórico", async () => {
    const { id } = routeFetch();
    const user = userEvent.setup();
    render(<DemandWorkspace requestId={id} />);

    await user.click(await screen.findByRole("button", { name: "Construjá" }));

    expect(await screen.findByText("Pronto para produção")).toBeInTheDocument();
    expect(screen.getByText("Construjá", { selector: "p" })).toBeInTheDocument();
  });

  it("demanda inexistente mostra o erro", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "demanda x não encontrada" }, 404)),
    );
    render(<DemandWorkspace requestId="x" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("demanda x não encontrada");
  });
});
