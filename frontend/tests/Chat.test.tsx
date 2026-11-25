import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Chat } from "@/components/Chat";
import type { ChatMessage } from "@/lib/types";
import { appConfig, finalView, firstView } from "./helpers";

const MESSAGES: ChatMessage[] = [
  { id: 1, role: "requester", text: "Preciso de uma arte da Krona para amanhã.", created_at: "" },
  { id: 2, role: "assistant", text: "Para qual marca é a demanda?\nQual é o objetivo da peça?", created_at: "" },
];

function setup(view = firstView(), messages = MESSAGES) {
  const onSend = vi.fn().mockResolvedValue(undefined);
  const onConfirmType = vi.fn().mockResolvedValue(undefined);
  render(
    <Chat
      view={view}
      messages={messages}
      config={appConfig()}
      busy={false}
      error={null}
      onSend={onSend}
      onConfirmType={onConfirmType}
    />,
  );
  return { onSend, onConfirmType, user: userEvent.setup() };
}

describe("Chat (§13, tela 1)", () => {
  it("mostra o histórico do solicitante e as perguntas", () => {
    setup();

    expect(screen.getByText("Preciso de uma arte da Krona para amanhã.")).toBeInTheDocument();
    expect(screen.getByText(/Para qual marca é a demanda\?/)).toBeInTheDocument();
  });

  it("envia a resposta digitada", async () => {
    const { onSend, user } = setup();

    await user.type(screen.getByRole("textbox", { name: "Sua mensagem" }), "Construjá");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(onSend).toHaveBeenCalledWith("Construjá");
  });

  it("não envia mensagem em branco", async () => {
    const { onSend, user } = setup();

    await user.type(screen.getByRole("textbox", { name: "Sua mensagem" }), "   ");

    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("chips de marca respondem com o nome da marca", async () => {
    const { onSend, user } = setup();

    await user.click(screen.getByRole("button", { name: "Ferjá" }));

    expect(onSend).toHaveBeenCalledWith("Ferjá");
  });

  it("chips de tipo confirmam o tipo", async () => {
    const view = firstView();
    view.next_action = "CONFIRM_TYPE";
    const { onConfirmType, onSend, user } = setup(view);

    expect(screen.getByText("Confirme o tipo da demanda:")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vídeo" }));

    expect(onConfirmType).toHaveBeenCalledWith("Vídeo");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("em PENDING_APPROVAL avisa que nova mensagem volta para validação", () => {
    setup(finalView());

    expect(screen.getByText(/voltar para validação/)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Sua mensagem" })).toBeEnabled();
  });

  it("bloqueia o envio em estado final", () => {
    const view = finalView();
    view.demand.status = "TASK_CREATED";
    view.next_action = "DONE";
    setup(view);

    expect(screen.getByRole("textbox", { name: "Sua mensagem" })).toBeDisabled();
  });

  it("mostra o erro da API", () => {
    render(
      <Chat
        view={firstView()}
        messages={MESSAGES}
        config={appConfig()}
        busy={false}
        error="Falha do LLM"
        onSend={vi.fn()}
        onConfirmType={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Falha do LLM");
  });
});
