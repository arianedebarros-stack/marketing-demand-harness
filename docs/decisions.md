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

## Decisões posteriores

**D21 · Next.js 15 em vez de 14** (2026-11-16, na revisão da T01; substitui "Next.js 14" do `CLAUDE.md`). O `npm audit` apontava uma vulnerabilidade crítica no `next@14.2.35`, sem correção na linha 14. O frontend passa para `next@15.5.29` com React 19 (exigido pelo App Router no Next 15) e `eslint-config-next@15.5.29`. A SPEC já aceita "Next.js 14+"; o `CLAUDE.md` foi atualizado para "Next.js 15". Depois da atualização restam 2 avisos (1 alto, 1 moderado), ambos no `postcss` embutido no próprio `next`, usado só no build. A correção só existe no Next 16, então eles ficam registrados aqui e serão reavaliados se houver patch na linha 15.

**D22 · Validação dos arquivos de `config/`** (2026-11-16, T02). Além dos tipos, `core/config.py` rejeita com `ConfigError` (mensagem com arquivo, campo e motivo): chaves desconhecidas em qualquer objeto (evita erro de digitação passar em silêncio); pesos de prioridade que não somam 1; `bands` fora de ordem decrescente ou sem faixa `min 0`; `urgency_by_hours` fora de ordem crescente ou sem um último item com `max_hours null`; `deadline_hour` fora de 0–23; `classification_threshold` fora de [0, 1]; `types` sem `"Outro"` (destino dos tipos desconhecidos no guardrail, §8.2); `skills` da equipe que não existem em `task_types.json`; ids de equipe duplicados. São checagens de consistência dos próprios JSONs, sem valor de negócio no código. A pasta de config pode ser trocada por `CONFIG_DIR` (padrão: `config/` na raiz do repositório).

**D23 · Formato de `questions[]` e campos editáveis no PATCH** (2026-11-16, T03). A §9 não define nenhum dos dois.
- Cada pergunta é `{fields: [..], text}`. Uma pergunta pode cobrir mais de um campo, como `channel + format` e `product + price` (§8.4).
- O `PATCH /requests/{id}` aceita os campos de conteúdo do briefing, mais `task_type`, `priority`, `assigned_to` e `approver`.
- Não são editáveis: estado, scores, travas (`*_locked`), `field_origin`, ids e listas calculadas pelo harness. Mandar um desses campos dá `422`.
- Só os campos enviados contam; mandar `null` limpa o campo.

**D24 · `published_error` faz parte da demanda** (2026-11-16, T03). A §8.5 usa `published_error` para impacto, risco e elevação para Crítica, mas a §6 não lista esse campo. Ele é guardado na demanda (padrão `false`) para que `POST /requests/{id}/triage` possa recalcular a prioridade sem chamar o LLM de novo.

**D25 · Schema do LLM só garante a forma** (2026-11-16, T03). Em `LLMInterpretation`:
- Os valores de `extracted` chegam como texto (números viram texto). Tipo, confiança e datas não são validados no schema. O guardrail (§8.2) cuida disso e registra cada descarte, para que um valor ruim não derrube a interpretação inteira.
- Chaves desconhecidas em `extracted` são guardadas, para o guardrail descartar e auditar. O `input_schema` da tool declara `additionalProperties: false`, para orientar o modelo.
- O `input_schema` é gerado do próprio modelo e não depende de outros schemas (sem `$ref`).
- No audit e no `link-existing`, ids de tarefa são inteiros e ids de demanda são UUID. A T14 pode rever isso quando criar as tabelas.

**D26 · Comportamento do FakeLLMClient onde a §12 não é explícita** (2026-11-16, T05).
- **Palavras-chave no código:** as palavras de tipo, canal e formato ficam em `llm/fake_client.py`. Elas simulam o que o LLM sabe e não são regras de negócio. Marcas e fornecedores vêm do contexto, que é montado a partir do `config/`.
- **Histórico inteiro:** os campos são extraídos mensagem por mensagem, e a mais recente vence. Classificação, `is_promotional` e o objetivo de reserva ("Divulgar promoção <fornecedor>") usam o histórico completo. Isso permite ao caso 06 chegar a 100% com informação espalhada em três mensagens.
- **Canais reconhecidos:** Instagram, WhatsApp, Facebook, LinkedIn, Site, App e E-mail. Formatos: Feed, Stories, Reels e Carrossel. Quando há mais de um, vale o primeiro da lista.
- **Vigência em ISO:** quando a data é resolvida, `validity` é gravada como `YYYY-MM-DD`, seguindo a convenção de datas internas.
- **"-feira" não é evento:** o sufixo "-feira" dos dias da semana é removido antes de classificar, para que "quarta-feira" não seja confundido com o tipo Evento ("feira").
- **Dono de dependência:** é o nome com inicial maiúscula depois de "por/pelo/pela/com/do/da" (ex.: "por Compras"). Sem esse nome, o dono é Compras quando o texto fala de preço e "Não informado" nos outros casos. "Ainda não aprovado o X" vira "Aprovação de X".
- **Campos que o Fake não preenche:** `published_error` é sempre `false` e `files` vem sempre vazio, porque a §12 não define regras para eles. Os arquivos obrigatórios vêm do Rule Engine (§8.3).
- **Consequência para os testes** (pedido da autora na revisão da T05): como o Fake nunca preenche `published_error`, os testes da T11 (e os guardrails/pipeline, quando aplicável) devem cobrir `published_error=true` montando a demanda ou a `LLMInterpretation` diretamente.

**D27 · Detalhes dos guardrails** (2026-11-16, T06).
- **Arquivo novo `config/guardrails.json`:** guarda as expressões temporais (D11), as palavras de anexo ("planilha/anexo/tabela", §8.2) e o tamanho mínimo de palavra para produto (4 letras, §8.2). O loader passa a ler 5 arquivos, e uma expressão temporal com sintaxe inválida gera `ConfigError`.
- **Números:** se o valor tem dígitos, cada grupo de dígitos precisa aparecer no texto do solicitante, mesmo que ele mencione planilha (D10). Se o valor não tem dígitos, só `price` passa, e apenas quando o texto menciona planilha, anexo ou tabela. `quantity`, `budget` e `participants_count` não têm essa exceção.
- **Datas:** `deadline`, `shoot_date` e `event_date` precisam estar em `YYYY-MM-DD` e ser datas reais. Todas elas, e também `validity`, exigem uma referência temporal no texto do solicitante.
- **Marca:** a marca do LLM é comparada sem acento e sem diferenciar maiúsculas. Quando é reconhecida, passa a ser grafada como em `brands.json`, e o ajuste vai para o audit (`brand_canonicalized`). O tipo também é comparado sem acento ("video" vira "Vídeo").
- **Eventos para o audit:** o engine devolve a interpretação já limpa, mais uma lista de eventos com campo, valor, motivo e substituto. Um evento sem substituto é um descarte (`guardrail_discard`); com substituto é um ajuste (`guardrail_adjust`: tipo, confiança, marca). É o pipeline quem grava esses eventos no `audit_log`.
- **Tipo definido pelo gestor:** o guardrail não muda a classificação nesse caso. A regra "campo do gestor nunca é sobrescrito" vale para os campos extraídos. A proteção do `task_type` definido pelo gestor (ou confirmado com `type_confirmed`) fica no merge do pipeline (T10).

**D28 · Detalhes do Rule Engine** (2026-11-17, T07; os dois primeiros pontos foram aprovados pela autora antes da implementação).
- **Push e E-mail só preenchem o canal vazio.** O canal do tipo (`Push → App`, `E-mail → E-mail`) é aplicado só quando o canal está vazio ou já veio de regra, como nos passos 1, 3 e 5. Ele nunca sobrescreve `message`, `llm` ou `manager`. Quando o tipo e o formato implicam canais diferentes, vale o do tipo (passo 2, que vem depois).
- **O CTA da marca prevalece.** Quando a regra se aplica, o `mandatory_cta` substitui valores de `llm` e `message`. Um CTA igual ao de outra marca (comparação sem acento e sem caixa) é sempre removido. Um CTA de regra que deixou de valer (marca trocada, marca sem CTA, regra que não se aplica mais) vira `null`. Um CTA que o próprio solicitante escreveu é mantido quando a marca não tem CTA obrigatório.
- **Campos de regra são recalculados.** Canal, público, tom e dimensões com origem `rule` são recalculados a cada execução. Se a regra deixa de valer (marca removida, formato trocado), o valor é apagado. Origem `manager` nunca é tocada.
- **Troca de formato e dimensão de `message`** (2026-11-17, revisão da T10, pedido da autora). O Rule Engine continua sem sobrescrever uma dimensão de `message`. Quem a apaga é o merge do pipeline (D31): quando o formato muda e a mensagem nova não traz dimensão, a dimensão antiga de origem `message` sai, e a regra do passo 5 a recalcula para o formato novo. Dimensão de `manager` nunca é tocada.
- **`is_promotional`.** O pipeline grava a flag do LLM na demanda antes de chamar o engine. Se a flag tem origem `rule`, o engine a recalcula do zero, para que ela não fique marcada depois que o fornecedor sai.
- **`required_files` guarda a origem de cada item** (revisto pela autora em 2026-11-17, na revisão da T07; substitui a versão anterior deste ponto, em que a lista só crescia). Cada item é `{name, origin}`, e não mais uma string, o que muda a §6. Os itens com origem `rule` são recalculados a cada execução: se o fornecedor muda, "Logo Krona" vira "Logo Tigre"; se a demanda deixa de ser promocional ou perde o fornecedor, os itens de regra saem. Os itens de `message`, `llm` e `manager` nunca são removidos. Se o arquivo já está na lista com outra origem (comparação sem acento e sem caixa), a regra não o duplica e o item fica com a origem que já tinha.
- **Parâmetros em `config/task_types.json` (`rules`).** Ficam lá `type_implies_channel`, `cta_types`, `supplier_promo_types` e `promo_supplier_files` (modelos com `{supplier}`). O loader rejeita tipos inexistentes e marcadores desconhecidos.
- **Comparações.** As chaves de `formats` e `format_implies_channel` são comparadas sem acento e sem caixa ("INSTAGRAM" + "stories" encontra `instagram|stories`).
- **Eventos para o audit.** O engine devolve uma lista de mudanças (`rule_applied`, com campo, valor anterior, regra e novo valor). Quem grava essas mudanças no `audit_log` é o pipeline.

**D29 · Detalhes do Validator e do Briefing Score** (2026-11-17, T08; o primeiro ponto foi aprovado pela autora antes da implementação).
- **Tipo incerto: só confirmar o tipo.** O tipo é incerto quando `task_type` está vazio, quando não existe em `task_types.json` ou quando a confiança fica abaixo de `classification_threshold` sem `type_confirmed` e sem origem `manager`. Nesse caso o Validator devolve `missing = ["task_type"]` e uma única pergunta, de confirmação do tipo. O score é calculado sobre `universal_required` + `task_type`, com o tipo contado como faltante, então nunca chega a 100%. Os campos do tipo só são cobrados depois da confirmação. Confiança igual ao limite (0,70) é aceita, porque a §7 fala em "< 0,70".
- **Faixas do score em `config/task_types.json` (`score_bands`).** As faixas são valor de negócio. O loader exige ordem decrescente de `min`, sem repetição, terminando em `min 0`, e só aceita os nomes da §8.4.
- **Arredondamento.** O score usa arredondamento comercial (meio para cima, 12,5 → 13), e não o arredondamento bancário do `round` do Python. 100% só com todos os obrigatórios preenchidos: 99,5% fica em 99 ("Quase pronto").
- **Preenchido** é valor diferente de `null` e, em texto, diferente de vazio ou só espaços.
- **Ordem.** `missing` segue a ordem dos obrigatórios (universais, depois os do tipo, depois os de promoção). As perguntas seguem a ordem de `validator.QUESTIONS`, com o prazo por último, como no caso 01.
- **Grupos.** `channel + format` e `product + price` viram uma pergunta só quando os dois faltam. Quando falta só um, a pergunta é só desse campo, com texto próprio. Assim nunca se pergunta um campo preenchido.
- **Marca faltante.** `audience` e `message_tone` continuam em `missing` (contam no score), mas não são perguntados enquanto a marca falta.
- **Resultado.** O engine devolve obrigatórios, faltantes, perguntas, score com faixa e `ready` (100% e tipo resolvido). Quem grava `missing_information` e `briefing_score` na demanda e muda o estado é o pipeline (T10).

**D30 · Detalhes do título e do briefing final** (2026-11-17, T09; o objetivo curto, os campos do tipo e o formato das datas foram aprovados pela autora antes da implementação). Complementa a D15.
- **Objetivo curto:** são as primeiras N palavras do objetivo, sem reticências. N fica em `config/task_types.json` (`title.objective_max_words`, valor 6).
- **"Promoção <fornecedor>":** o meio do título só usa o fornecedor quando a demanda é promocional. Um vídeo com fornecedor que não é promoção usa o objetivo curto. O modelo fica em `title.promo_template`, e o loader só aceita o marcador `{supplier}`. A ordem continua a da §8.9: campanha, depois promoção, depois objetivo curto.
- **Partes vazias:** são omitidas do título junto com o separador ("Arte | Ferjá").
- **Campos próprios do tipo:** os obrigatórios do tipo (`required`, e `promo_required` quando promocional) que não estão na lista da §8.9 entram depois do CTA e antes do PRAZO, na ordem de `task_types.json`, com rótulo em maiúsculas (`briefing.TYPE_FIELD_LABELS`). Campos de outros tipos não entram.
- **Datas:** PRAZO, data da gravação e data do evento aparecem como dd/mm/aaaa no texto. Uma VIGÊNCIA em ISO também é convertida; vigência em texto livre aparece como está. Os dados internos continuam em ISO.
- **Formato dos valores:**
  - RESPONSÁVEL mostra o nome do colaborador em `team.json`, e o id quando ele não está lá.
  - DEPENDÊNCIAS é escrita como `dependência (dono, status)`, com várias separadas por "; ".
  - ARQUIVOS são os nomes separados por "; ".
  - PRIORIDADE mostra só o nível.
  - BRIEFING SCORE vem como "N%" e sempre aparece.
  - APROVAÇÃO só aparece quando `approver` está preenchido. O padrão `approver_default` é aplicado na triagem, não aqui.
- **Título reaproveitável:** `build_briefing` aceita um título já calculado, para o pipeline não precisar recalculá-lo.

**D31 · Detalhes do pipeline** (2026-11-17, T10).
- **Sem persistência.** `services/pipeline.py` recebe a demanda e o histórico completo de mensagens do solicitante. Ele devolve a nova demanda, as perguntas, o `next_action`, a faixa do score e a lista de eventos de audit (`AuditEvent`). Quem grava a demanda e o `audit_log` são a T14 e a T15. A demanda de entrada não é alterada.
- **Para em `READY_FOR_TRIAGE`.** A triagem automática até `PENDING_APPROVAL` (D01) entra quando os engines da T11–T13 existirem. Até lá, `next_action` é `null` em `READY_FOR_TRIAGE`.
- **Estados de entrada.** Uma mensagem só é aceita em `RECEIVED` (passa por `PARSED`), `NEEDS_INFORMATION` ou `PENDING_APPROVAL` (volta a `VALIDATING` mantendo as travas, §7). Em qualquer outro estado, o pipeline levanta `InvalidTransition` antes de chamar o LLM, e quem chama grava `audit_payload()`.
- **Campos perguntados por último.** São recalculados com o Validator sobre a demanda anterior, quando ela está em `NEEDS_INFORMATION`. Assim não é preciso guardar mais nada.
- **Texto do solicitante para guardrails e origem.** É o histórico inteiro, juntado. Um valor que veio de uma mensagem anterior continua tendo respaldo.
- **Merge** (D06, D07, D27, D28):
  - Um valor em branco não apaga o anterior.
  - O `task_type` e a confiança só são atualizados se o tipo não é do gestor nem está confirmado. A classificação vai sempre para o audit, com `applied` indicando se foi aplicada.
  - `is_promotional` recebe a flag do LLM com origem `llm` antes das regras, a não ser que a origem seja `manager`.
  - `published_error` só muda quando a interpretação nova traz um valor explícito (`true` ou `false`). Se o valor vier vazio ou ausente, a flag anterior fica (revisto pela autora em 2026-11-17, na revisão da T10; substitui "segue a interpretação mais recente"). Para isso, `LLMInterpretation.published_error` passa a ser `bool | null`, com padrão `null`. O FakeLLMClient nunca preenche esse campo (D26), então não apaga a flag.
  - **Troca de formato** (revisão da T10). Quando o formato muda em relação ao valor anterior e a dimensão tem origem `message`, o merge verifica se a mensagem mais recente traz a dimensão: todos os grupos de dígitos dela precisam aparecer na mensagem. Se não traz, a dimensão é apagada (evento `field_cleared`, motivo `format_changed`) antes das regras, e o Rule Engine a recalcula ("troca para stories" vai de 1080 × 1350 para 1080 × 1920 px). Se a mensagem traz uma dimensão nova ou repete a antiga, ela fica. Formato preenchido pela primeira vez não conta como troca. Dimensão de `manager` nunca é tocada. Dimensão de origem `llm` fica fora desta regra, porque o pedido foi só para `message`.
  - As dependências do LLM são acrescentadas sem duplicar (comparação sem acento e sem caixa), e as existentes ficam com o status que já tinham.
  - Os `files` do LLM entram em `required_files` com origem `llm`, sem duplicar.
  - Nem o merge nem uma nova interpretação removem dependências ou arquivos de outras origens.
- **Eventos de audit.**
  - `message_received` (user);
  - `interpretation` (llm, com provedor e saída);
  - `classification` (llm);
  - `guardrail_discard` e `guardrail_adjust`;
  - `field_registered`, só quando o valor ou a origem mudou;
  - `field_cleared` (dimensão apagada por troca de formato);
  - `rule_applied`;
  - `briefing_score`;
  - `status_transition`.
- **`revalidate`.** Roda regras, validação e estado sem chamar o LLM. Será usado por `POST /validate`, pelo PATCH e pela confirmação de tipo (T15).
