# CLAUDE.md — instruções para o agente de código

Você está implementando o **Marketing Demand Harness**. Leia nesta ordem antes de qualquer código:

1. `SPEC.md` — o que construir (fonte da verdade).
2. `TASKS.md` — a ordem de execução. Trabalhe **uma tarefa por vez**.
3. `config/*.json` — regras de negócio. Nunca copie esses valores para o código ou para prompts.

## Regras inegociáveis

- **O LLM só interpreta; o harness decide.** Nenhuma decisão (estado, score, prioridade, responsável, criação de tarefa) depende de texto livre do modelo.
- Saída do LLM sempre validada por schema Pydantic e passada pelos guardrails (`engines/guardrails.py`) antes de ser usada.
- Engines em `backend/app/engines/` são funções puras: sem I/O, sem LLM, sem banco. Recebem dados e config, devolvem resultado.
- Regras de marca, tipos, equipe e pesos vêm de `config/`. Se precisar de um valor novo, adicione no JSON.
- Nunca criar tarefa externa sem aprovação (`APPROVED`). Nunca chamar a API real do Asana ou do LLM em testes.
- Toda ação relevante gera registro em `audit_log` via `services/audit.py`.
- Não invente requisitos. Se a SPEC for ambígua, pare e pergunte; registre a decisão em `docs/decisions.md`.

## Stack e comandos

- Backend: Python 3.12+ (máquina da autora: 3.14), FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pytest.
- Frontend: Next.js 14 + TypeScript + Tailwind em `frontend/`.
- Banco: PostgreSQL via `docker compose up -d db`.

Comandos esperados no `Makefile` (crie na tarefa T01):

```
make setup     # cria venv, instala deps do backend e do frontend
make db        # sobe o Postgres
make migrate   # alembic upgrade head
make dev       # backend (uvicorn :8000) + frontend (:3000)
make test      # pytest com cobertura
make lint      # ruff + mypy (backend), eslint (frontend)
```

## Como trabalhar cada tarefa

1. Leia a tarefa em `TASKS.md` e as seções da SPEC que ela cita.
2. Escreva primeiro os testes que provam o critério de aceite da tarefa.
3. Implemente o mínimo para passar. Rode `make test` e `make lint`.
4. Marque a tarefa como `[x]` em `TASKS.md`.
5. Faça um commit pequeno, em português, no formato Conventional Commits:
   `feat(priority): implementa Priority Engine com regras de elevação (T07)`
6. Pare e mostre um resumo do que mudou antes de seguir para a próxima tarefa.

## Convenções

- Código, nomes e commits podem ser em inglês ou português, mas mantenha o mesmo idioma em todo o código. Textos da UI e perguntas ao usuário em português do Brasil.
- Type hints em todo o backend; `ruff` sem avisos.
- Datas internas em ISO `YYYY-MM-DD`; fuso em `APP_TIMEZONE`.
- Segredos só em `.env` (nunca em commit). Use `.env.example` como referência.
- Testes que dependem de "hoje" recebem a data por parâmetro (`now`), nunca usam o relógio real.

## Definição de pronto

Ver `SPEC.md §19`. Uma tarefa só está pronta com testes passando, lint limpo, `TASKS.md` atualizado e commit feito.
