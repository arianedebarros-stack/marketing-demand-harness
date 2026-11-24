# Marketing Demand Harness

AI Agent Harness que transforma pedidos informais ao Marketing em demandas completas, validadas, priorizadas, atribuídas e aprovadas antes de virar tarefa.

**Princípio:** o LLM só interpreta; o harness decide (estados, regras, validação, guardrails, aprovação humana e auditoria).

## Documentos

- [`SPEC.md`](SPEC.md) — especificação completa.
- [`CLAUDE.md`](CLAUDE.md) — instruções para o agente de código.
- [`TASKS.md`](TASKS.md) — plano de implementação e progresso.
- [`config/`](config) — regras de marca, tipos de demanda, equipe, prioridade e guardrails.

## Como rodar

> Preenchido durante a implementação (tarefa T21).

```bash
cp .env.example .env
make setup
make db && make migrate
make dev
make test
```

## Rodada manual com o LLM real (T16)

Os testes automáticos nunca chamam a API da Anthropic. Para testar com o modelo de verdade:

1. No `.env`, preencha a sua chave e confira o modelo:

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   LLM_MODEL=claude-opus-5-5
   ```

2. Rode:

   ```bash
   make llm-smoke
   # ou com outra mensagem:
   make llm-smoke MSG="Faz uma arte da Ferjá para sexta com os preços da planilha"
   ```

O comando faz **uma** chamada à API (com custo), sem fallback para o Fake. Ele mostra o modelo, a interpretação validada pelo schema e o que os guardrails descartariam. A chave nunca é impressa. Se a API recusar a credencial, a mensagem pede para conferir `ANTHROPIC_API_KEY`. Detalhes em `docs/decisions.md` (D17, D37).

## Status

Acompanhe o progresso em [`TASKS.md`](TASKS.md).
