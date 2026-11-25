import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DemandSheet } from "@/components/DemandSheet";
import { appConfig, finalView, firstView } from "./helpers";

describe("Ficha da demanda (§13, tela 2)", () => {
  it("mostra o estado no stepper com a etapa atual marcada", () => {
    render(<DemandSheet view={firstView()} config={appConfig()} />);

    const stepper = screen.getByRole("list", { name: "Etapas da demanda" });
    const current = within(stepper).getByText("Validação").closest("li");
    expect(current).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Faltam informações")).toBeInTheDocument();
  });

  it("mostra o Briefing Score com a faixa", () => {
    render(<DemandSheet view={firstView()} config={appConfig()} />);

    const score = screen.getByRole("meter", { name: "Briefing Score" });
    expect(score).toHaveAttribute("aria-valuenow", String(firstView().demand.briefing_score));
    expect(screen.getByText("Incompleto")).toBeInTheDocument();
  });

  it("mostra cada campo com a tag de origem e destaca os faltantes", () => {
    render(<DemandSheet view={firstView()} config={appConfig()} />);

    const supplier = screen.getByRole("row", { name: /Fornecedor/ });
    expect(within(supplier).getByText("Krona")).toBeInTheDocument();
    expect(within(supplier).getByText("Mensagem")).toBeInTheDocument();

    const brand = screen.getByRole("row", { name: /Marca/ });
    expect(brand).toHaveAttribute("data-missing", "true");
    expect(within(brand).getByText("Faltando")).toBeInTheDocument();
  });

  it("antes da triagem avisa que ela roda com 100%", () => {
    render(<DemandSheet view={firstView()} config={appConfig()} />);

    expect(screen.getByText(/A triagem roda quando o briefing chega a 100%/)).toBeInTheDocument();
  });

  it("mostra a triagem: prioridade com motivos, responsável com cargas, dependências e arquivos", () => {
    render(<DemandSheet view={finalView()} config={appConfig()} />);

    const triage = screen.getByRole("region", { name: "Triagem" });
    expect(within(triage).getByText("Alta")).toBeInTheDocument();
    expect(within(triage).getByText("76,5")).toBeInTheDocument();
    expect(within(triage).getByText("Pontuação 76,5 → Alta")).toBeInTheDocument();

    expect(within(triage).getByRole("heading", { name: "Responsável" })).toBeInTheDocument();
    expect(within(triage).getAllByText("Designer A").length).toBeGreaterThan(0);
    const loads = within(triage).getByRole("table", { name: "Cargas da equipe" });
    expect(within(loads).getByText("53%")).toBeInTheDocument();
    expect(within(loads).getByText("80%")).toBeInTheDocument();

    expect(within(triage).getByText("Aprovação de preço")).toBeInTheDocument();
    expect(within(triage).getByText(/Compras/)).toBeInTheDocument();
    expect(within(triage).getByText("Pendente")).toBeInTheDocument();

    expect(within(triage).getByText("Logo Krona")).toBeInTheDocument();
    expect(within(triage).getByText("Imagens dos produtos")).toBeInTheDocument();
  });

  it("mostra o score 100% como Pronto para produção na etapa de aprovação", () => {
    render(<DemandSheet view={finalView()} config={appConfig()} />);

    expect(screen.getByText("Pronto para produção")).toBeInTheDocument();
    const current = screen.getByText("Aprovação").closest("li");
    expect(current).toHaveAttribute("aria-current", "step");
  });

  it("sem responsável mostra 'a definir' com o aprovador padrão", () => {
    const view = finalView();
    view.demand.assigned_to = null;
    view.audit = view.audit.filter((a) => a.action !== "assignment_calculated");

    render(<DemandSheet view={view} config={appConfig()} />);

    expect(screen.getByText("A definir (Gestor de Marketing)")).toBeInTheDocument();
  });

  it("demanda cancelada mostra o aviso fora do fluxo", () => {
    const view = finalView();
    view.demand.status = "CANCELLED";

    render(<DemandSheet view={view} config={appConfig()} />);

    expect(screen.getByRole("status")).toHaveTextContent("Cancelada");
  });
});
