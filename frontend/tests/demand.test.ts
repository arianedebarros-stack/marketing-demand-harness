import { describe, expect, it } from "vitest";
import {
  auditValue,
  brandChips,
  canSendMessage,
  currentStep,
  fieldRows,
  formatDate,
  gateForm,
  gatePatch,
  latestAssignment,
  latestPriority,
  memberName,
  newestFirst,
  priorityLevels,
  showsApprovalGate,
  STEPS,
  typeChips,
} from "@/lib/demand";
import type { RequestStatus } from "@/lib/types";
import { appConfig, finalView, firstView } from "./helpers";

describe("currentStep (stepper da ficha)", () => {
  it.each<[RequestStatus, number]>([
    ["RECEIVED", 0],
    ["PARSED", 0],
    ["VALIDATING", 1],
    ["NEEDS_INFORMATION", 1],
    ["READY_FOR_TRIAGE", 2],
    ["TRIAGED", 2],
    ["PENDING_APPROVAL", 3],
    ["APPROVED", 3],
    ["TASK_CREATED", 4],
  ])("%s fica na etapa %i", (status, step) => {
    expect(currentStep(status)).toBe(step);
  });

  it.each<RequestStatus>(["CANCELLED", "REJECTED", "ERROR"])(
    "%s sai do fluxo (sem etapa atual)",
    (status) => {
      expect(currentStep(status)).toBeNull();
    },
  );

  it("tem as 5 etapas do fluxo da §7", () => {
    expect(STEPS.map((s) => s.label)).toEqual([
      "Recebida",
      "Validação",
      "Triagem",
      "Aprovação",
      "Tarefa criada",
    ]);
  });
});

describe("fieldRows (campos com origem e faltantes)", () => {
  it("lista preenchidos com a origem e faltantes destacados, sem repetir campo", () => {
    const rows = fieldRows(firstView().demand);
    const byField = Object.fromEntries(rows.map((r) => [r.field, r]));

    expect(byField.task_type).toMatchObject({ value: "Arte", origin: "llm", missing: false });
    expect(byField.supplier).toMatchObject({ value: "Krona", origin: "message", missing: false });
    expect(byField.brand).toMatchObject({ value: null, missing: true, label: "Marca" });
    expect(byField.validity.missing).toBe(true);
    expect(new Set(rows.map((r) => r.field)).size).toBe(rows.length);
  });

  it("faltantes vêm da API (missing_information); a UI não recalcula obrigatórios", () => {
    const view = firstView();
    view.demand.missing_information = ["objective"];

    const missing = fieldRows(view.demand).filter((r) => r.missing).map((r) => r.field);

    expect(missing).toEqual(["objective"]);
  });

  it("mostra datas em dd/mm/aaaa e omite campos vazios não obrigatórios", () => {
    const rows = fieldRows(finalView().demand);
    const byField = Object.fromEntries(rows.map((r) => [r.field, r]));

    expect(byField.deadline.value).toBe("20/10/2026");
    expect(byField.validity.value).toBe("23/10/2026");
    expect(byField.dimensions).toMatchObject({ value: "1080 × 1350 px", origin: "rule" });
    expect(byField.campaign).toBeUndefined();
    expect(rows.every((r) => !r.missing)).toBe(true);
  });

  it("não mostra na lista de campos o que pertence à triagem", () => {
    const fields = fieldRows(finalView().demand).map((r) => r.field);

    expect(fields).not.toContain("priority");
    expect(fields).not.toContain("assigned_to");
    expect(fields).not.toContain("approver");
  });
});

describe("formatDate", () => {
  it("converte ISO e deixa texto livre como está", () => {
    expect(formatDate("2026-10-20")).toBe("20/10/2026");
    expect(formatDate("até o fim do mês")).toBe("até o fim do mês");
  });
});

describe("triagem a partir do audit", () => {
  it("pega a prioridade e os motivos do último cálculo", () => {
    const view = finalView();
    view.audit.push({
      ...view.audit.find((a) => a.action === "priority_calculated")!,
      id: 999,
      new_value: { level: "Crítica", score: 91, factors: {}, reasons: ["Prazo em menos de 24 h"] },
    });

    expect(latestPriority(view.audit)).toEqual({
      level: "Crítica",
      score: 91,
      reasons: ["Prazo em menos de 24 h"],
    });
  });

  it("devolve null antes da triagem", () => {
    expect(latestPriority(firstView().audit)).toBeNull();
    expect(latestAssignment(firstView().audit)).toBeNull();
  });

  it("pega o responsável, o motivo e as cargas", () => {
    const assignment = latestAssignment(finalView().audit);

    expect(assignment?.name).toBe("Designer A");
    expect(assignment?.reason).toContain("menor carga");
    expect(assignment?.loads.map((l) => [l.name, l.load])).toEqual([
      ["Designer A", 0.5333],
      ["Designer B", 0.8],
    ]);
  });
});

describe("chips do chat", () => {
  it("mostra as marcas do config quando a marca é perguntada", () => {
    expect(brandChips(firstView(), appConfig())).toEqual(["Construjá", "Ferjá"]);
  });

  it("não mostra marcas quando a marca não é perguntada", () => {
    expect(brandChips(finalView(), appConfig())).toEqual([]);
  });

  it("mostra os tipos do config só para confirmar o tipo", () => {
    const view = firstView();
    expect(typeChips(view, appConfig())).toEqual([]);

    view.next_action = "CONFIRM_TYPE";

    expect(typeChips(view, appConfig())).toEqual(["Arte", "Vídeo", "Outro"]);
  });
});

describe("canSendMessage", () => {
  it.each<[RequestStatus, boolean]>([
    ["NEEDS_INFORMATION", true],
    ["PENDING_APPROVAL", true],
    ["TASK_CREATED", false],
    ["CANCELLED", false],
    ["APPROVED", false],
  ])("%s → %s", (status, expected) => {
    expect(canSendMessage(status)).toBe(expected);
  });
});

describe("memberName", () => {
  it("usa o nome da equipe e cai no id quando não encontra", () => {
    expect(memberName("designer-a", appConfig())).toBe("Designer A");
    expect(memberName("fulano", appConfig())).toBe("fulano");
  });
});

describe("Approval Gate: formulário Editar (§14, D36)", () => {
  it("o gate só aparece aguardando aprovação ou quando a criação falhou (D04)", () => {
    expect(showsApprovalGate("PENDING_APPROVAL")).toBe(true);
    expect(showsApprovalGate("APPROVED")).toBe(true);
    for (const status of ["NEEDS_INFORMATION", "TASK_CREATED", "CANCELLED"] as const) {
      expect(showsApprovalGate(status)).toBe(false);
    }
  });

  it("níveis de prioridade vêm do config, na ordem das faixas", () => {
    expect(priorityLevels(appConfig())).toEqual(["Crítica", "Alta", "Normal", "Baixa"]);
  });

  it("o formulário começa em Automático quando o gestor não travou", () => {
    const demand = finalView().demand;
    expect(gateForm(demand)).toEqual({ priority: "", assigned_to: "", deadline: "2026-10-20" });
    demand.priority_locked = true;
    demand.assignment_locked = true;
    expect(gateForm(demand)).toMatchObject({ priority: "Alta", assigned_to: "designer-a" });
  });

  it("o PATCH leva só o que mudou; vazio vira null", () => {
    const before = { priority: "Alta", assigned_to: "", deadline: "2026-10-20" };

    expect(gatePatch(before, before)).toEqual({});
    expect(gatePatch(before, { ...before, priority: "" })).toEqual({ priority: null });
    expect(gatePatch(before, { ...before, assigned_to: "designer-b", deadline: "" })).toEqual({
      assigned_to: "designer-b",
      deadline: null,
    });
  });
});

describe("Registro", () => {
  it("ordena do mais recente ao mais antigo sem alterar a lista original", () => {
    const entries = finalView().audit;
    const sorted = newestFirst(entries);
    expect(sorted[0].id).toBe(Math.max(...entries.map((e) => e.id)));
    expect(entries[0].id).toBeLessThan(entries[1].id);
  });

  it("valores do audit em JSON compacto; vazio sem valor", () => {
    expect(auditValue({ a: 1 })).toBe('{"a":1}');
    expect(auditValue(null)).toBe("");
  });
});
