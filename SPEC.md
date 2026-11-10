# SPEC — Marketing Demand Harness

> Especificação para implementação por agente de código (Claude Code, Devin, Cursor).
> Fonte da verdade do **o quê**. O **como trabalhar** está em `CLAUDE.md`; a **ordem** está em `TASKS.md`.
> Versão 1.1 · 2026-10-19

---

## 1. Contexto

Pedidos ao Marketing chegam informais e incompletos ("Preciso de uma arte da Krona para amanhã"). Falta marca, objetivo, público, canal, formato, preço, vigência, prazo. Isso gera retrabalho e atraso.

O **Marketing Demand Harness** recebe o pedido em linguagem natural e o transforma em uma demanda estruturada, validada, priorizada, atribuída e aprovada por um humano antes de virar tarefa no sistema de gestão.

## 2. Princípio de arquitetura (não negociável)

**O LLM só interpreta. O harness decide.**

- O LLM recebe o histórico da conversa e devolve **JSON validado por schema** (classificação + campos extraídos + dependências explícitas).
- Toda decisão — estado, validação, regras de marca, Briefing Score, prioridade, responsável, duplicidade, criação de tarefa — é **código determinístico** testável sem LLM.
- Regras de negócio ficam em `config/*.json`, nunca no prompt.
- Texto livre do LLM **nunca** dispara ação.

## 3. Escopo

| Etapa | Conteúdo | Obrigatório nesta entrega |
|---|---|---|
| 1 | Chat, interpretação, classificação, templates, campos ausentes, Briefing Score, briefing final | Sim |
| 2 | Prioridade, responsáveis, capacidade, dependências, regras de marca, aprovação | Sim |
| 3 | Integração Asana, autenticação, logs na UI, dashboard | Asana e logs: sim. SSO e dashboard: opcional |

**Fora do escopo:** criar a peça de Marketing, publicar conteúdo, enviar comunicação externa, apagar tarefas.

## 4. Stack

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12+ (máquina da autora: 3.14), FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Banco | PostgreSQL 16 (Docker Compose); SQLite em memória nos testes |
| LLM | Anthropic SDK; modelo em `LLM_MODEL`; saída estruturada via tool use com `input_schema` |
| Testes | pytest, pytest-asyncio, httpx (TestClient), cobertura ≥ 80% em `engines/` |
| Frontend | Next.js 14+ (App Router), Node 20+ (máquina da autora: 22) + TypeScript + Tailwind |
| Integração | Asana REST API (`TASK_MANAGER=asana`) ou conector local (`TASK_MANAGER=local`) |

## 5. Estrutura do repositório

```
marketing-demand-harness/
├── SPEC.md  CLAUDE.md  TASKS.md  README.md  .env.example  docker-compose.yml  Makefile
├── config/                 # memória institucional (editável sem deploy de código)
│   ├── brands.json  task_types.json  team.json  priorities.json
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app
│   │   ├── api/requests.py         # endpoints /requests
│   │   ├── api/tasks.py            # endpoints /tasks
│   │   ├── core/config.py          # settings (.env) + loader de config/*.json
│   │   ├── core/state_machine.py   # estados e transições permitidas
│   │   ├── schemas/                # Pydantic: demand.py, llm.py, api.py
│   │   ├── models/                 # SQLAlchemy
│   │   ├── llm/base.py             # interface LLMClient
│   │   ├── llm/anthropic_client.py
│   │   ├── llm/fake_client.py      # determinístico, para testes/offline
│   │   ├── llm/prompts.py
│   │   ├── engines/
│   │   │   ├── guardrails.py       # sanitização da saída do LLM
│   │   │   ├── validator.py        # campos obrigatórios + perguntas
│   │   │   ├── score.py            # Briefing Score
│   │   │   ├── rules.py            # Rule Engine (marca, formatos)
│   │   │   ├── priority.py
│   │   │   ├── assignment.py
│   │   │   ├── dependency.py
│   │   │   ├── dedupe.py
│   │   │   └── briefing.py         # título + template final
│   │   ├── services/pipeline.py    # orquestra engines + estados
│   │   ├── services/audit.py
│   │   └── integrations/           # task_manager.py (interface), local.py, asana.py
│   ├── alembic/
│   └── tests/
└── frontend/
```

## 6. Modelo da demanda

```json
{
  "request_id": "uuid",
  "requester": "string", "department": "string",
  "company": "string|null", "brand": "string|null",
  "task_type": "string|null", "campaign": "string|null", "supplier": "string|null",
  "objective": "string|null", "audience": "string|null", "message_tone": "string|null",
  "channel": "string|null", "format": "string|null", "dimensions": "string|null",
  "product": "string|null", "price": "string|null", "validity": "string|null", "cta": "string|null",
  "deadline": "YYYY-MM-DD|null",
  "duration": null, "concept": null, "location": null, "participants": null, "shoot_date": null,
  "headline": null, "landing_page": null, "link": null, "publish_period": null,
  "size": null, "quantity": null, "material": null, "finishing": null,
  "event_name": null, "event_date": null, "event_time": null, "participants_count": null, "budget": null, "deliverables": null,
  "priority": "Crítica|Alta|Normal|Baixa|null", "priority_score": "number|null", "priority_locked": false,
  "assigned_to": "employee_id|null", "assignment_locked": false,
  "approver": "string|null",
  "dependencies": [{ "dependency": "string", "owner": "string", "status": "Pendente|Resolvida" }],
  "required_files": ["string"],
  "missing_information": ["field_key"],
  "is_promotional": false,
  "briefing_score": 0,
  "classification_confidence": 0.0,
  "type_confirmed": false,
  "status": "RECEIVED",
  "field_origin": { "<field>": "message|llm|rule|harness|manager|requester" },
  "external_task_id": "string|null"
}
```

`field_origin` é obrigatório: a UI mostra de onde veio cada valor.

## 7. Estados

```
RECEIVED → PARSED → VALIDATING → NEEDS_INFORMATION ⇄ VALIDATING
VALIDATING → READY_FOR_TRIAGE → TRIAGED → PENDING_APPROVAL → APPROVED → TASK_CREATED
Qualquer estado não final → CANCELLED | ERROR
PENDING_APPROVAL → REJECTED
TASK_CREATED com dependência pendente → BLOCKED (flag da tarefa; volta a TASK_CREATED ao resolver)
```

- `core/state_machine.py` define a tabela de transições permitidas. Transição inválida levanta `InvalidTransition` e é registrada no audit log.
- Classificação com confiança < `classification_threshold` (0,70) → permanece em `NEEDS_INFORMATION` com `missing_information = ["task_type"]` e `next_action = "CONFIRM_TYPE"`.
- Nova mensagem do solicitante em `PENDING_APPROVAL` volta a `VALIDATING` (mantendo `priority_locked` e `assignment_locked`).

## 8. Engines

### 8.1 Interpretação (LLM)

**Entrada para o LLM** (montada em `llm/prompts.py`): data de hoje e dia da semana, tipos permitidos, nomes de marca permitidos, fornecedores conhecidos, campos possíveis, dados já registrados, campos perguntados por último, histórico **somente das mensagens do solicitante**.

**Saída exigida** (tool `register_interpretation`, schema Pydantic `LLMInterpretation`):

```json
{
  "classification": { "type": "Arte", "confidence": 0.96 },
  "extracted": { "brand": "Construjá", "supplier": "Krona", "deadline": "2026-10-20" },
  "is_promotional": true,
  "published_error": false,
  "dependencies": [{ "dependency": "Aprovação de preço", "owner": "Compras", "status": "Pendente" }],
  "files": ["Planilha de preços"]
}
```

Regras do prompt: nunca inventar; campo ausente não aparece; datas em ISO calculadas a partir de hoje; "urgente" não é prazo; vigência ≠ prazo; fornecedor vai em `supplier`, nunca em `brand`; só dependências explícitas.

`FakeLLMClient` implementa a mesma interface com regras por regex (ver §12) para testes e uso offline.

### 8.2 Guardrails (`engines/guardrails.py`)

Aplicados à saída do LLM **antes** do merge. Cada descarte gera audit log com o motivo.

| Campo | Regra |
|---|---|
| `task_type` | Fora da lista → `"Outro"`; confiança limitada a [0, 1] |
| `brand` | Deve existir em `brands.json` (comparação sem acento/caixa); senão descarta |
| `price`, `quantity`, `budget`, `participants_count` | Exige dígito no texto do solicitante (ou "planilha/anexo/tabela" para `price`) |
| `product` | Exige palavra (≥ 4 letras) do valor presente no texto do solicitante, ou menção a planilha/anexo |
| datas | Devem ser ISO válidas e o texto do solicitante deve conter referência temporal |
| qualquer campo | Chave desconhecida é ignorada; campo com `field_origin = manager` nunca é sobrescrito |

### 8.3 Rule Engine (`engines/rules.py`)

Lê `config/`. Ordem:
1. `format` sem `channel` → canal de `format_implies_channel` (origin `rule`).
2. `Push` → `channel = "App"`; `E-mail` → `channel = "E-mail"`.
3. Marca conhecida → `audience` e `message_tone` da marca, se vazios ou já `rule`.
4. CTA: `mandatory_cta` da marca quando promocional ou tipo ∈ {Arte, Social Media, Campanha, Banner Site}. Marca sem CTA → `null`. **Nunca** aplicar CTA de outra marca.
5. `channel|format` em `formats` e `dimensions` vazio → preenche.
6. Promocional com fornecedor → `required_files += ["Logo <fornecedor>", "Imagens dos produtos"]`.

`is_promotional = llm.is_promotional OR (supplier AND task_type ∈ {Arte, Social Media})`.

### 8.4 Validator e Briefing Score

- Obrigatórios = `universal_required` ∪ `types[t].required` ∪ (`promo_required` se promocional).
- `briefing_score = round(preenchidos / total × 100)`.
- Faixas: 0–49 Incompleto · 50–79 Parcial · 80–99 Quase pronto · 100 Pronto para produção.
- Só avança para `READY_FOR_TRIAGE` com 100%.
- **Perguntas**: só campos faltantes; se `brand` falta, não perguntar `audience`/`message_tone` (virão da marca). Agrupar `channel+format` e `product+price` em uma pergunta cada. Nunca perguntar campo preenchido. Textos das perguntas em `validator.QUESTIONS`.

### 8.5 Priority Engine (`engines/priority.py`)

```
Priority Score = urgência×0,40 + impacto×0,30 + dependências×0,15 + risco×0,15   (pesos em priorities.json)
```

- **Urgência**: horas até `deadline` às 18h (`APP_TIMEZONE`): <24 → 100; ≤48 → 90; ≤120 → 60; ≤240 → 35; senão 15; sem prazo → 20.
- **Impacto**: `types[t].impact`; promocional → máx(impacto, 80); `published_error` → 100.
- **Dependências** pendentes: 0→0, 1→40, 2→70, 3+→90.
- **Risco**: `published_error` → 100; promocional com preço → 70; com fornecedor → 50; senão 30.
- Faixa pela pontuação (bands). **Regras que elevam** a faixa (nunca rebaixam): `published_error` ou prazo < 24 h ou evento hoje → Crítica; prazo ≤ 72 h → mínimo Alta.
- A palavra "urgente" não altera nada. `priority_locked = true` (definida pelo gestor) → engine não recalcula.
- Retorna `{score, level, factors, reasons[]}`.

### 8.6 Assignment Engine (`engines/assignment.py`)

1. Candidatos = `team` com `task_type` em `skills`.
2. `carga = (open_base + tarefas abertas atribuídas no banco) / capacity`.
3. Ordena por carga ↑, depois nº de tarefas Alta/Crítica abertas ↑.
4. Sem candidato → `approver_default`, com motivo.
5. `assignment_locked = true` → não recalcula.
- Retorna `{employee_id, name, reason, loads: [{name, load}]}`.

### 8.7 Dependency Checker

Dependências explícitas do LLM (deduplicadas por texto normalizado). Tarefa com dependência `Pendente` é criada com `blocked = true`. `POST /tasks/{id}/dependencies/{i}/resolve` resolve; sem pendências → desbloqueia.

### 8.8 Duplicidade (`engines/dedupe.py`)

Antes de criar: tarefa aberta com mesma `brand` + `task_type` + (`supplier` ou `campaign`) criada nos últimos 30 dias, **ou** Jaccard de palavras do título ≥ 0,75. Se encontrar, `approve` retorna `409` com a tarefa candidata; o cliente reenvia com `{"force_new": true}` ou chama `link-existing`.

### 8.9 Título e briefing final

- Título: `[TIPO] | [CAMPANHA ou "Promoção <fornecedor>" ou objetivo curto] | [MARCA]` — ex.: `Arte | Promoção Krona | Construjá`.
- Briefing final: template em texto (seção 29 da spec original): TÍTULO, OBJETIVO, MARCA, PÚBLICO, CANAL, FORMATO, DIMENSÃO, MENSAGEM E TOM, PRODUTOS, PREÇOS, VIGÊNCIA, CTA, PRAZO, PRIORIDADE, RESPONSÁVEL, APROVAÇÃO, DEPENDÊNCIAS, ARQUIVOS, BRIEFING SCORE. Campos vazios não aparecem.

## 9. API

Todas as respostas de `/requests/*` retornam `RequestView`: `{ demand, next_action, questions[], score_band, audit[] }`.
`next_action ∈ { REQUEST_INFORMATION, CONFIRM_TYPE, AWAIT_APPROVAL, DONE, CANCELLED }`.

| Método | Rota | Corpo | Efeito |
|---|---|---|---|
| POST | `/requests` | `{requester_name, department, channel, message}` | Cria, interpreta, roda pipeline |
| GET | `/requests/{id}` | — | Estado atual |
| POST | `/requests/{id}/answers` | `{message}` | Acrescenta ao histórico, reinterpreta, roda pipeline |
| POST | `/requests/{id}/confirm-type` | `{task_type}` | Confirma tipo (`type_confirmed = true`) |
| POST | `/requests/{id}/validate` | — | Reroda validação |
| POST | `/requests/{id}/triage` | — | Reroda triagem (requer 100%) |
| PATCH | `/requests/{id}` | campos editáveis | Edição humana (`origin = manager`); `priority`/`assigned_to` travam |
| POST | `/requests/{id}/approve` | `{force_new?: bool}` | Dedupe → APPROVED → cria tarefa → TASK_CREATED; 409 se duplicada |
| POST | `/requests/{id}/link-existing` | `{task_id}` | Vincula a tarefa existente → CANCELLED |
| POST | `/requests/{id}/cancel` | — | CANCELLED |
| GET | `/tasks` | — | Lista tarefas |
| POST | `/tasks/{id}/dependencies/{index}/resolve` | — | Resolve dependência |
| GET | `/config` | — | Config atual (somente leitura) |

Erros: `422` validação; `409` transição inválida ou duplicidade; `502` falha do LLM (com fallback para `FakeLLMClient` se `LLM_FALLBACK=true`).

## 10. Banco de dados

Tabelas: `users`, `requests` (id, requester, department, channel, status, demand JSONB, created_at, updated_at), `messages` (id, request_id, role, text, created_at), `tasks` (id, request_id, external_task_id, title, type, brand, supplier, campaign, assigned_to, priority, deadline, blocked, status, briefing, briefing_score, created_at), `dependencies` (id, task_id, description, owner, status), `audit_log` (id, request_id, task_id, actor[llm|harness|user|manager], action, previous_value JSONB, new_value JSONB, timestamp).

Config de marcas/tipos/equipe permanece em `config/*.json` nesta entrega.

## 11. Integração com o sistema de tarefas

Interface `TaskManagerConnector.create_task(task) -> external_id`.
- `LocalTaskManager`: grava em `tasks` e devolve `MKT-<n>`.
- `AsanaTaskManager`: `POST https://app.asana.com/api/1.0/tasks` com `{"data": {"name", "notes": briefing, "due_on", "projects": [ASANA_PROJECT_GID]}}`, header `Authorization: Bearer ASANA_TOKEN`. Salva o `gid` retornado em `external_task_id`. Testes usam mock HTTP (respx); **nunca** chamar a API real nos testes.

## 12. FakeLLMClient (interpretação por regras)

Mesma saída de §8.1, sem rede. Mínimo:
- Tipo por palavras-chave (ordem importa): banner+site → Banner Site; vídeo/gravar → Vídeo; evento/feira → Evento; folheto/cartaz/impresso → Material Impresso; arte/peça/feed/stories/carrossel → Arte; post → Social Media; campanha → Campanha. Uma regra → 0,92; várias → 0,80; "promoção" sem tipo → Arte 0,55; nada → Outro 0,40.
- Marca e fornecedor por nome (sem acento). Canal (instagram, whatsapp, facebook, site…). Formato (feed, stories, reels, carrossel). Dimensão `\d{3,4}x\d{3,4}`.
- Vigência: "vale/válida/vigência … até X" (extrair antes do prazo). Prazo: hoje, amanhã, dia da semana, dd/mm.
- "planilha/anexo" → `product` e `price` = "Conforme planilha anexada".
- Objetivo: "divulgar/promover/anunciar/lançar …"; ou promocional + fornecedor → "Divulgar promoção <fornecedor>".
- Dependência: "aguardando/depende de/falta aprovação/ainda não aprovado …"; dono por palavra (Compras se preço).
- Se nada novo foi extraído e só um campo foi perguntado, a resposta inteira é o valor desse campo.

## 13. Frontend

1. **Nova demanda**: nome + departamento; chat; chips para marca e confirmação de tipo.
2. **Ficha da demanda** (ao lado do chat): estado (stepper), Briefing Score com faixa, campos com tag de origem, faltantes destacados, triagem (prioridade + motivos, responsável + cargas, dependências, arquivos).
3. **Approval Gate**: título, responsável, prioridade, prazo, score → botões **Aprovar e criar**, **Editar**, **Cancelar**; alerta de duplicidade com **Usar existente** / **Criar nova**.
4. **Quadro de tarefas**: lista com status (Aberta/Bloqueada/Concluída), detalhe com briefing e histórico, resolver dependência.
5. **Registro**: audit log em ordem decrescente.

## 14. Human-in-the-loop e guardrails de ação

Exigem ação humana: aprovação da tarefa, mudança de responsável, prioridade crítica, alteração de prazo, cancelamento. O agente/LLM **não pode**: inventar preço/prazo/produto/aprovação, alterar prioridade definida pelo gestor, criar tarefa sem aprovação, alterar config, apagar tarefas, publicar ou enviar comunicação externa.

## 15. Auditoria

Toda ação gera linha em `audit_log`: recebimento, interpretação (provedor), classificação, cada campo registrado, cada descarte de guardrail, cada regra aplicada, score, transições, prioridade (com motivos), responsável (com cargas), duplicidade, aprovação, criação de tarefa (id externo), edições humanas (antes/depois).

## 16. Critérios de aceite → testes

| AC | Critério | Teste obrigatório |
|---|---|---|
| AC01 | Recebe pedido em linguagem natural | `test_api.py::test_create_request` |
| AC02 | Classifica certo em ≥ 90% | `test_classification.py` com ≥ 20 frases rotuladas (`tests/data/classification.jsonl`) |
| AC03 | Não inventa dados | `test_guardrails.py` (preço, produto, data, marca inexistente) |
| AC04 | Identifica faltantes | `test_validator.py::test_missing_fields_arte_promo` |
| AC05 | Pergunta só o que falta | `test_validator.py::test_questions_only_missing` |
| AC06 | Mantém dados anteriores | `test_pipeline.py::test_memory_across_answers` |
| AC07 | Regras por marca | `test_rules.py::test_ferja_no_construja_cta` |
| AC08 | Briefing Score | `test_score.py` (6/8 = 75%) |
| AC09 | Prioridade | `test_priority.py` (exemplo 90/80/40/70 = 76,5 → Alta; <24 h → Crítica; "urgente" não altera) |
| AC10 | Dependências explícitas | `test_dependency.py` |
| AC11 | Responsável compatível | `test_assignment.py` (A 53% vs B 80% → A; Vídeo → Videomaker) |
| AC12 | Briefing estruturado | `test_briefing.py` (título e template) |
| AC13 | Exige aprovação | `test_api.py::test_cannot_create_task_without_approval` |
| AC14 | Cria tarefa após aprovação | `test_integrations.py` (local + Asana mockado) |
| AC15 | Registra tudo | `test_audit.py` |

## 17. Casos de teste da especificação (E2E com FakeLLMClient)

| # | Entrada | Esperado |
|---|---|---|
| 01 | "Faz uma arte da Krona." | Não cria tarefa; `NEEDS_INFORMATION`; pergunta marca, objetivo, canal/formato, produtos/preços, vigência, prazo |
| 02 | "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. Os produtos e preços estão na planilha anexada e a promoção vale até sexta." | Arte · Construjá · Instagram · Feed · 1080 × 1350 · Krona · score 100% · prioridade Alta |
| 03 | Pedido equivalente com marca Ferjá | Público "Consumidor final"; CTA Ferjá; sem CTA Construjá |
| 04 | "Faz promoção da Krona." | `price = null` |
| 05 | Caso 02 com tarefa "Arte \| Promoção Krona \| Construjá" já aberta | `approve` retorna 409 com a tarefa existente |
| 06 | Fluxo: "Preciso de uma arte da Krona para amanhã." → "Construjá" → "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. Ainda aguardando aprovação de preço por Compras." | 100%; Alta; Designer A; dependência Compras; tarefa criada bloqueada após aprovação |

## 18. Métricas (endpoint `/metrics/summary`, opcional)

% briefings completos na 1ª mensagem · média de perguntas até 100% · tempo solicitação → tarefa · tarefas por colaborador · % críticas/altas.

## 19. Definição de pronto da entrega

- `make test` verde, cobertura ≥ 80% em `backend/app/engines`.
- Casos 01–06 passando como testes E2E.
- `docker compose up` sobe Postgres; `make dev` sobe backend e frontend; fluxo do caso 06 funciona na UI.
- README com instruções de execução e prints/GIF do fluxo.
