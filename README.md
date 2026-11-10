# Marketing Demand Harness

AI Agent Harness que transforma pedidos informais ao Marketing em demandas completas, validadas, priorizadas, atribuídas e aprovadas antes de virar tarefa.

**Princípio:** o LLM só interpreta; o harness decide (estados, regras, validação, guardrails, aprovação humana e auditoria).

## Documentos

- [`SPEC.md`](SPEC.md) — especificação completa.
- [`CLAUDE.md`](CLAUDE.md) — instruções para o agente de código.
- [`TASKS.md`](TASKS.md) — plano de implementação e progresso.
- [`config/`](config) — regras de marca, tipos de demanda, equipe e prioridade.

## Como rodar

> Preenchido durante a implementação (tarefa T21).

```bash
cp .env.example .env
make setup
make db && make migrate
make dev
make test
```

## Status

Acompanhe o progresso em [`TASKS.md`](TASKS.md).
