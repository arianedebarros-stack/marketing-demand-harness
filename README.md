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

### Telas no navegador (T18, T19)

Com `make dev` rodando, abra <http://localhost:3000>:

- **Nova demanda** (`/`): nome, departamento e o pedido em texto livre.
- **Demanda** (`/demandas/<id>`): o chat à esquerda (com chips de marca e de confirmação de tipo) e a ficha ao lado (estado, Briefing Score, campos com a origem, faltantes e triagem). Quando a demanda chega à aprovação, aparece o **Approval Gate** (título, responsável, prioridade, prazo e score) com **Aprovar e criar**, **Editar** (prioridade, responsável e prazo, com origem Gestor) e **Cancelar**. Se houver tarefa aberta parecida, o alerta oferece **Usar existente** ou **Criar nova**.
- **Quadro de tarefas** (`/tarefas`): tarefas com status Aberta, Bloqueada ou Concluída. O detalhe mostra o briefing, as dependências (com **Resolver**), **Concluir tarefa** e o histórico da demanda.
- **Registro** (`/registro`): o audit log inteiro, do mais recente ao mais antigo. `/registro?demanda=<id>` mostra só uma demanda.

O frontend chama a API em `http://localhost:8000` (mude com `NEXT_PUBLIC_API_URL` em `frontend/.env.local`). A API aceita o navegador vindo de `CORS_ORIGINS` (padrão `http://localhost:3000`). Para testar sem gastar com o LLM, use `LLM_PROVIDER=fake` no `.env`.

## LLM real da Anthropic (opcional)

O sistema funciona sem chave da API da Anthropic: a interpretação usa o `FakeLLMClient`, que segue regras fixas, e os testes automáticos nunca chamam a API. Sem chave, deixe no `.env`:

```
LLM_PROVIDER=fake
```

Com `LLM_PROVIDER=anthropic` e sem chave, o sistema também funciona. Mas cada mensagem tenta a API, falha e cai no Fake, e isso fica registrado como `llm_fallback` no audit.

### Rodada manual com o LLM real (T16)

Quando houver uma chave, para testar com o modelo de verdade:

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

## Asana (opcional)

Por padrão (`TASK_MANAGER=local`), as tarefas aprovadas ficam só no próprio sistema, com ids `MKT-<n>`. Os testes nunca chamam o Asana: usam respostas simuladas (respx) e um token falso.

Para criar as tarefas aprovadas também no Asana, ponha no `.env`:

```
TASK_MANAGER=asana
ASANA_TOKEN=<Personal Access Token do Asana>
ASANA_PROJECT_GID=<gid do projeto>
```

- **Token:** crie um Personal Access Token no Asana (Meu perfil → Configurações → Apps → Console do desenvolvedor). A conta dona do token precisa ter acesso ao projeto.
- **`gid` do projeto:** é o número longo que aparece na URL do projeto no Asana.
- **Sem uma das duas variáveis:** com `TASK_MANAGER=asana`, a aplicação não sobe e mostra um erro claro.
- **Se o Asana falhar:** a demanda fica em `APPROVED`, a API responde 502 e basta aprovar de novo (D04, D38).

## Limitações conhecidas

- **Tarefa duplicada no Asana (D38, risco aceito).** O sistema não repete sozinho uma criação que falhou no Asana. Mas se o Asana criar a tarefa e a resposta se perder no caminho (por exemplo, um timeout depois do envio), a demanda fica em `APPROVED`, e a nova aprovação cria uma segunda tarefa lá. Para reconhecer a duplicata, o texto de cada tarefa no Asana termina com `ID DA DEMANDA: <id>`. Duas tarefas com o mesmo id são a mesma demanda, e uma delas pode ser apagada no Asana.

## Status

Acompanhe o progresso em [`TASKS.md`](TASKS.md).
