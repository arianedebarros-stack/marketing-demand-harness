# Registro de decisões

Decisões tomadas sobre pontos ambíguos ou ausentes da `SPEC.md` (v1.1). Todas foram aprovadas pela autora em 2026-11-16, antes da T01.
Quando uma decisão mudar, registre a nova entrada com data e indique qual ela substitui.

## Fluxo e estados

**D01 · Fluxo automático até a aprovação.** Quando o Briefing Score chega a 100%, o pipeline roda a triagem automaticamente e leva a demanda até `PENDING_APPROVAL` (como o caso 06 pressupõe). `POST /requests/{id}/validate` e `POST /requests/{id}/triage` apenas rodam essas etapas de novo.

**D02 · Rota de rejeição.** `REJECTED` existe nos estados (§7), mas a §9 não tem rota. Criamos `POST /requests/{id}/reject` (`PENDING_APPROVAL → REJECTED`).

**D03 · BLOCKED não é estado da demanda.** A demanda fica em `TASK_CREATED`; o bloqueio é só a flag `tasks.blocked`, que volta a `false` quando todas as dependências são resolvidas.

**D04 · Falha ao criar a tarefa externa** (ex.: Asana fora do ar). A demanda continua em `APPROVED`, o erro vai para o `audit_log` e `approve` pode ser chamado de novo. A demanda só vai para `ERROR` em caso de falha interna do harness.

**D05 · Estados finais.** `TASK_CREATED`, `CANCELLED`, `REJECTED` e `ERROR`. Nenhum deles aceita transição para `CANCELLED` ou `ERROR`.

## Dados e memória

**D06 · Merge entre mensagens (AC06).** Campo ausente na nova interpretação mantém o valor anterior. Um valor novo vindo da interpretação substitui valores com origem `llm`, `message` ou `rule`. Nunca substitui origem `manager`.

**D07 · Origem `message` vs. `llm`.** `message` quando o valor aparece literalmente no texto do solicitante (comparação sem acento e sem caixa); `llm` quando foi inferido. `requester` é usado para nome e departamento vindos do formulário.

**D08 · Tipos dos campos sem tipo na §6** (`duration`, `budget`, `quantity` etc.): todos `str | None`. Campos de data (`deadline`, `shoot_date`, `event_date`) são `date | None`, serializados em ISO `YYYY-MM-DD`.

**D09 · Dimensões normalizadas.** "1080x1350" é normalizado para "1080 × 1350 px", o mesmo formato usado em `config/`.

## Regras ambíguas

**D10 · Guardrail de preço e quantidade mais estrito.** "Exige dígito no texto" (§8.2) é fraco: no caso 02 o "1080x1350" já deixaria passar um preço inventado. Para `price`, `quantity`, `budget` e `participants_count`, os dígitos do valor precisam aparecer no texto do solicitante. A exceção para "planilha/anexo/tabela" em `price` continua.

**D11 · Datas relativas.** "sexta" (ou outro dia da semana) é a próxima ocorrência a partir de amanhã. "dd/mm" que já passou neste ano vai para o ano seguinte. A lista de expressões temporais aceitas pelo guardrail fica em `config/`.

**D12 · Duplicidade com campos nulos.** No critério `brand + task_type + (supplier ou campaign)`, `null == null` não conta como igual. No Jaccard de palavras do título, o separador "|" é ignorado.

**D13 · Conclusão de tarefa.** A tela 4 mostra "Concluída" e a carga usa "tarefas abertas", mas a §9 não tem rota para concluir. Criamos `POST /tasks/{id}/complete`.

**D14 · Prioridade Crítica e ação humana (§14).** O Priority Engine pode sugerir Crítica; a aprovação no Approval Gate conta como a ação humana exigida. Não há etapa extra.

**D15 · Template do briefing final.** A "seção 29 da spec original" (§8.9) não está disponível. O briefing usa uma linha `RÓTULO: valor` por campo, na ordem listada na §8.9; campos vazios não aparecem.

## Convenções e ambiente

**D16 · Idioma.** Identificadores de código em inglês (como na SPEC); textos da UI, perguntas ao usuário e commits em português do Brasil.

**D17 · Modelo padrão em `LLM_MODEL`.** Decidido na T16, consultando a documentação atual da API da Anthropic. Até lá, `.env.example` mantém o valor original (`claude-sonnet-5-5`).

**D18 · Driver do Postgres.** `psycopg` 3 (`psycopg[binary]`). Verificado na T01: instala sem erro no Python 3.14.

**D19 · Docker no WSL.** Verificado na T01: `docker compose up -d db` sobe o Postgres 16 neste ambiente.

**D20 · Horário fixo nos testes.** Os casos 02 e 06 dependem do horário ("amanhã" vira Crítica se o pedido chegar depois das 18h). Os testes fixam `now` pela manhã; assim o caso 02 dá 70,5 e o caso 06 dá 76,5, ambos Alta, como a SPEC espera.
