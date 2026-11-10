# TASKS — plano de implementação

Execute em ordem. Cada tarefa = testes + código + commit. Referências em `SPEC.md`.

## Fase 0 — Fundação

- [ ] **T01 · Esqueleto do projeto** — estrutura de pastas da SPEC §5, `pyproject.toml`, `Makefile`, `docker-compose.yml` (Postgres 16), FastAPI com `GET /health`. *Aceite:* `make setup && make test` passa com 1 teste de health.
- [ ] **T02 · Config loader** — `core/config.py` lê `.env` (pydantic-settings) e `config/*.json` em modelos Pydantic validados. *Aceite:* teste carrega as 4 configs; JSON inválido gera erro claro.
- [ ] **T03 · Schemas** — `schemas/demand.py` (SPEC §6), `schemas/llm.py` (`LLMInterpretation`, §8.1), `schemas/api.py` (`RequestView`, §9). *Aceite:* testes de validação dos schemas.
- [ ] **T04 · State machine** — `core/state_machine.py` com a tabela de transições (§7). *Aceite:* teste de todas as transições válidas e de pelo menos 5 inválidas.

## Fase 1 — Etapa 1 do MVP (interpretação e briefing)

- [ ] **T05 · FakeLLMClient** — `llm/base.py` (interface) + `llm/fake_client.py` (§12). *Aceite:* casos 01–04 da §17 retornam a interpretação esperada.
- [ ] **T06 · Guardrails** — `engines/guardrails.py` (§8.2). *Aceite:* `test_guardrails.py` cobre preço, produto, data, marca inexistente, campo do gestor (AC03).
- [ ] **T07 · Rule Engine** — `engines/rules.py` (§8.3). *Aceite:* `test_rules.py`, incluindo Ferjá sem CTA Construjá (AC07).
- [ ] **T08 · Validator + Briefing Score** — `engines/validator.py` e `engines/score.py` (§8.4). *Aceite:* AC04, AC05, AC08.
- [ ] **T09 · Título e briefing final** — `engines/briefing.py` (§8.9). *Aceite:* AC12.
- [ ] **T10 · Pipeline** — `services/pipeline.py` orquestra interpretação → guardrails → merge → regras → validação → estado, com memória da demanda. *Aceite:* AC06 e caso 01.

## Fase 2 — Etapa 2 do MVP (triagem e aprovação)

- [ ] **T11 · Priority Engine** — `engines/priority.py` (§8.5). *Aceite:* AC09 (76,5 → Alta; <24 h → Crítica; "urgente" não altera; `priority_locked` respeitado).
- [ ] **T12 · Assignment Engine** — `engines/assignment.py` (§8.6). *Aceite:* AC11.
- [ ] **T13 · Dependências e duplicidade** — `engines/dependency.py`, `engines/dedupe.py` (§8.7, §8.8). *Aceite:* AC10 e caso 05.
- [ ] **T14 · Banco e auditoria** — models SQLAlchemy + Alembic (§10), `services/audit.py` (§15). *Aceite:* AC15; migração sobe do zero.
- [ ] **T15 · API** — endpoints da §9 com TestClient. *Aceite:* AC01, AC13; casos 01–06 como testes E2E com FakeLLMClient.

## Fase 3 — LLM real, integração e interface

- [ ] **T16 · AnthropicClient** — `llm/anthropic_client.py` com tool `register_interpretation` e `input_schema` gerado de `LLMInterpretation`; prompt em `llm/prompts.py` (§8.1); fallback para Fake se `LLM_FALLBACK=true`. *Aceite:* teste com SDK mockado; rodada manual documentada no README.
- [ ] **T17 · Task manager** — `integrations/local.py` e `integrations/asana.py` (§11). *Aceite:* AC14 com Asana mockado (respx).
- [ ] **T18 · Frontend: Nova demanda + Ficha** — telas 1 e 2 da §13 consumindo a API.
- [ ] **T19 · Frontend: Approval Gate, Quadro e Registro** — telas 3, 4 e 5 da §13. *Aceite:* caso 06 executado ponta a ponta na UI.
- [ ] **T20 · Avaliação de classificação** — `tests/data/classification.jsonl` com ≥ 20 frases rotuladas; teste mede acurácia ≥ 90% com o Fake; script `make eval-llm` mede com o LLM real. *Aceite:* AC02.
- [ ] **T21 · Documentação final** — README com setup, comandos, arquitetura, prints do fluxo e resultado de `make test`. *Aceite:* SPEC §19 cumprida.
