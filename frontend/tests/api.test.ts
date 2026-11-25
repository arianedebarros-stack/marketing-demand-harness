import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  approve,
  cancelRequest,
  completeTask,
  confirmType,
  duplicateConflict,
  linkExisting,
  listAudit,
  listTasks,
  patchRequest,
  resolveDependency,
  createRequest,
  getConfig,
  getMessages,
  getRequest,
  sendAnswer,
} from "@/lib/api";
import { dupConflict, firstView, jsonResponse } from "./helpers";

const BASE = "http://localhost:8000";

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function lastCall(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
  return fetchMock.mock.calls.at(-1) as [string, RequestInit];
}

describe("cliente da API (§9)", () => {
  it("createRequest manda nome, departamento, canal do chat e mensagem", async () => {
    const fetchMock = stubFetch(jsonResponse(firstView(), 201));

    const view = await createRequest({
      requesterName: "Ana",
      department: "Comercial",
      message: "Preciso de uma arte da Krona para amanhã.",
    });

    const [url, init] = lastCall(fetchMock);
    expect(url).toBe(`${BASE}/requests`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      requester_name: "Ana",
      department: "Comercial",
      channel: "chat",
      message: "Preciso de uma arte da Krona para amanhã.",
    });
    expect(view.demand.status).toBe("NEEDS_INFORMATION");
  });

  it("sendAnswer e confirmType usam as rotas da demanda", async () => {
    const fetchMock = stubFetch(jsonResponse(firstView()));
    await sendAnswer("abc", "Construjá");
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/requests/abc/answers`);
    expect(JSON.parse(String(lastCall(fetchMock)[1].body))).toEqual({ message: "Construjá" });

    fetchMock.mockResolvedValue(jsonResponse(firstView()));
    await confirmType("abc", "Vídeo");
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/requests/abc/confirm-type`);
    expect(JSON.parse(String(lastCall(fetchMock)[1].body))).toEqual({ task_type: "Vídeo" });
  });

  it("getRequest, getMessages e getConfig fazem GET", async () => {
    const fetchMock = stubFetch(jsonResponse(firstView()));
    await getRequest("abc");
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/requests/abc`);

    fetchMock.mockResolvedValue(jsonResponse([]));
    await getMessages("abc");
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/requests/abc/messages`);

    fetchMock.mockResolvedValue(jsonResponse({}));
    await getConfig();
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/config`);
  });

  it("erro da API vira ApiError com status e detalhe", async () => {
    stubFetch(jsonResponse({ detail: "demanda x não encontrada" }, 404));

    const error = await getRequest("x").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, message: "demanda x não encontrada" });
  });

  it("erro 422 do FastAPI junta as mensagens de validação", async () => {
    stubFetch(
      jsonResponse({ detail: [{ msg: "campo obrigatório" }, { msg: "texto vazio" }] }, 422),
    );

    await expect(sendAnswer("abc", " ")).rejects.toThrow("campo obrigatório; texto vazio");
  });

  it("API fora do ar vira ApiError com mensagem clara", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(getConfig()).rejects.toThrow(/Não foi possível falar com a API/);
  });

  it("rotas do Approval Gate: approve, link-existing, cancel e PATCH", async () => {
    const fetchMock = stubFetch(jsonResponse(firstView()));

    await approve("abc");
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/requests/abc/approve`);
    expect(JSON.parse(String(lastCall(fetchMock)[1].body))).toEqual({ force_new: false });

    fetchMock.mockResolvedValue(jsonResponse(firstView()));
    await approve("abc", true);
    expect(JSON.parse(String(lastCall(fetchMock)[1].body))).toEqual({ force_new: true });

    fetchMock.mockResolvedValue(jsonResponse(firstView()));
    await linkExisting("abc", 7);
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/requests/abc/link-existing`);
    expect(JSON.parse(String(lastCall(fetchMock)[1].body))).toEqual({ task_id: 7 });

    fetchMock.mockResolvedValue(jsonResponse(firstView()));
    await cancelRequest("abc");
    expect(lastCall(fetchMock)).toEqual([`${BASE}/requests/abc/cancel`, expect.objectContaining({ method: "POST" })]);

    fetchMock.mockResolvedValue(jsonResponse(firstView()));
    await patchRequest("abc", { priority: "Crítica", deadline: null });
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe(`${BASE}/requests/abc`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ priority: "Crítica", deadline: null });
  });

  it("duplicateConflict reconhece o 409 de duplicidade e ignora outros erros", async () => {
    stubFetch(jsonResponse(dupConflict(), 409));
    const error = await approve("abc").catch((e: unknown) => e);

    expect(duplicateConflict(error)?.duplicate.task_id).toBe(dupConflict().duplicate.task_id);
    expect(duplicateConflict(new ApiError(409, "transição inválida", { detail: "x" }))).toBeNull();
    expect(duplicateConflict(new ApiError(502, "falhou", dupConflict()))).toBeNull();
    expect(duplicateConflict(new Error("x"))).toBeNull();
  });

  it("rotas do quadro de tarefas", async () => {
    const fetchMock = stubFetch(jsonResponse([]));

    await listTasks();
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/tasks`);

    fetchMock.mockResolvedValue(jsonResponse({}));
    await resolveDependency(3, 0);
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/tasks/3/dependencies/0/resolve`);
    expect(lastCall(fetchMock)[1].method).toBe("POST");

    fetchMock.mockResolvedValue(jsonResponse({}));
    await completeTask(3);
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/tasks/3/complete`);
  });

  it("listAudit monta o filtro, o cursor e o limite (D40)", async () => {
    const fetchMock = stubFetch(jsonResponse([]));

    await listAudit();
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/audit`);

    fetchMock.mockResolvedValue(jsonResponse([]));
    await listAudit({ requestId: "abc", before: 40, limit: 100 });
    expect(lastCall(fetchMock)[0]).toBe(`${BASE}/audit?request_id=abc&before=40&limit=100`);
  });
});
