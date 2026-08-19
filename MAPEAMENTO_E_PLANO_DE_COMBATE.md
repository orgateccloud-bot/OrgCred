# OrgCred — Mapeamento, scorecard e plano de entrada em produção

> Revisado em **2026-08-18**, com **todos os defeitos de código do levantamento
> fechados**, a infraestrutura arrumada até onde não depende de credencial, e as
> rotinas periódicas agendadas e verificadas em produção.
> O levantamento base é de 2026-08-12: 53 agentes sobre 10 domínios, com rodada
> adversarial — todo achado grave passou por um cético encarregado de refutá-lo,
> e **32 sobreviveram**. Este documento marca quais deles foram fechados e
> quais continuam abertos.

---

## 0. Estado da infraestrutura (2026-08-18)

Tudo abaixo foi **verificado**, não apenas configurado.

| Item | Estado | Prova |
|---|---|---|
| Gatilho do GitHub | funciona | deploys com hash de commit (`a3397d5`, `694776d`, `c409339`…) |
| Serviço duplicado `OrgCred` | **removido** | `list_services` devolve só `orgcred-api` e `Postgres` |
| Modo de execução | `production` | `/docs`, `/redoc` e `/openapi.json` caem no fallback do SPA |
| Health check | `/health/ready` | log do Railway: `GET /health/ready 200 OK` |
| Migrations | fase de pré-deploy | dois contêineres distintos no log: um roda `alembic` e **sai**, o outro sobe o uvicorn |
| Logging estruturado | emite | `{"event": "app_startup", …}` em JSON |
| Rotinas periódicas | **agendadas e verificadas** | execução real com `falhas=[]`: backup de 28K gerado, restaurado e validado |
| Vigilância das rotinas | o sistema sabe o próprio estado | trilha `execucao_rotina` (025, OC023) e aviso na tela quando alguma atrasa |

**Dois enganos que quase entraram no relatório**, e valem como método:

`/docs` respondia **200** depois de ligar o modo produção — parecia exposição
aberta. Era o **fallback do SPA**: `text/html`, 1.079 bytes, idêntico ao
`index.html`. Se o `/openapi.json` estivesse mesmo exposto, viria
`application/json` com dezenas de KB.

`get_service_config` continua mostrando `Health check path: /health`. O
`railway.json` sobrepõe **no deploy** sem reescrever o registro do serviço — a
prova está no log da sonda, não na configuração lida pela API.

**Antes de ligar o modo produção, verifiquei que era seguro** sem ver segredo
nenhum: assinei um token com a secret pública do repositório e chamei
`/api/me`. Resposta `401 TOKEN_INVALIDO` — a secret de produção é real, logo a
guarda fail-closed não derrubaria o serviço. Se tivesse sido aceito, ligar o
modo produção teria tirado produção do ar em vez de protegê-la.

---

## 1. Retrato em uma frase

Todos os defeitos de código que o levantamento encontrou estão fechados: o teto
do Art. 5º é defendido pelas bordas, a trilha de auditoria não acusa mais
adulteração falsa nem aceita lançamento antedatado, e a interface funciona de
ponta a ponta. O que impede operar é **configuração e dado de negócio** — mais
riscos residuais que exigem integração externa, não código.

---

## 2. O que mudou em 2026-08-12/18

| | Antes | Agora |
|---|---|---|
| Testes backend | 198 | **570** |
| Cobertura | 92% | **94,2%** (piso de 85% ativo na CI) |
| Testes frontend | 50 | **210** |
| E2E | 5 (todos quebrados) | **6, verdes** |
| Migrations | 14 | **25** |
| SQLSTATEs no banco | 18 | **22** |
| Suíte local | 148s | **27s** |

### Fechado

- **O sistema estava inoperante.** O bundle de produção apontava a API para
  `localhost:8000`; o operador autenticava e nenhuma chamada funcionava.
- **Não havia tela para arquivar identificação**, com o gate OC019 ligado —
  todo tomador cadastrado pela interface nascia impossível de operar.
- **`POST /liquidar` devolvia 100% do capital** sem uma parcela paga.
- **`UPDATE` de `valor_principal` em operação ativa** não passava por gate
  nenhum e não deixava rastro no ledger.
- **`esc_capital_social` só tinha trigger de `INSERT`** — `UPDATE`/`DELETE`
  derrubavam o teto sem OC005.
- **`reducao` com valor negativo inflava o teto** (só o Pydantic barrava).
- **Status `baixada` contornava a amarra de lastro**; `movimento_id` podia ser
  repontado; `TRUNCATE` apagava as trilhas append-only.
- **A baixa não tinha autor** — único ato irreversível do ciclo sem
  responsável.
- **A evidência de identificação era oca**: sha256 vinha pronto do cliente e
  não existia storage. Agora o upload é do arquivo, o hash é calculado no
  servidor e os bytes vão para o Supabase Storage. Sem credencial, o
  arquivamento é **recusado** em vez de aceitar sem guardar.
- **Quatro erros de conteúdo fiscal** (parâmetro de hoje aplicado a período
  passado, dupla contagem após novação, âncora do regime de caixa, mora e
  multa descartadas).
- **A prova de concorrência não valia**: o único teste aplicava as migrations
  001–003 e estava excluído do pytest, provando o lock de um trigger
  redefinido cinco vezes depois.
- **A pipeline podia ficar verde sem rodar nada** (200 skips, exit 0).
- **`/docs`, `/redoc` e `/openapi.json` públicos em produção**; rate limiting
  era código morto; auditoria sem paginação.
- **O logging não emitia nada** em produção.

### Fechado depois — os cinco que o levantamento deixou em aberto

| Achado | Como foi fechado |
|---|---|
| **Hash-chain ordenada por `created_at = now()`** — acusava adulteração falsa sob concorrência | Migration 020: coluna `seq` monotônica, elo anterior vira "a maior chave menor que a minha". O backfill usa a MESMA expressão de ordenação da verificação anterior, o que preserva os hashes já gravados por construção. A revisão pegou um efeito colateral grave: ancorar em `seq` cortava um amarrio acidental e passava a aceitar **append antedatado** sem acusar. Fechado com `new.created_at := now()` no trigger — antedatar virou impossível, não apenas detectável. |
| `registro_operacao` podia **nascer** `confirmado` | Migration 021: a máquina de estados passou a guardar o `INSERT` e **recusa** (OC018) em vez de rebaixar em silêncio. Fechada também a variante de nascer `pendente` com protocolo e `confirmado_em` pré-cozidos. O helper da suíte, que explorava o buraco, passou a emitir os dois comandos que os endpoints emitem. |
| O contrato imprimia texto livre em vez do protocolo | Passou a citar entidade, protocolo e data de confirmação. Contratos já emitidos seguem válidos com o texto antigo — nada recalcula hash existente (OC017). |
| Retenção ancorada no **arquivamento** | Migration 022: a coluna vira **piso** e a retenção efetiva é `greatest(piso, último encerramento + 5 anos)`; enquanto a relação não encerrou, é `infinity`. Tomador que encerra tudo e volta a tomar crédito reinicia o relógio. |

### Nenhum defeito de código em aberto

O último era a regra de atipicidade por **liquidação antecipada**, que comparava
o primeiro vencimento com `current_date` em vez da data em que a liquidação
aconteceu — detectava enquanto a varredura rodasse antes do vencimento e parava
de detectar depois, com o fato inalterado. Fechado pela migration 023, ancorando
na trilha de transições, com `min()` para que uma data forjada só possa
ANTECIPAR (produzindo trabalho a mais para o analista) e nunca atrasar
(escapando da regra). Entrou junto uma regra nova: write-off antes do primeiro
vencimento, separada de propósito — lá o dinheiro voltou cedo demais, aqui não
voltou.

### Construído depois do levantamento

Quatro coisas que não eram defeito, e sim ausência — atacadas para tirar
domínios do amarelo:

**Importação de extrato OFX (migration 024) e a tela que a torna usável.** O único produtor de
`movimento_bancario` era um formulário que aceitava data, valor e documento
arbitrários: o lastro era estrutural ("existe um registro apontado"), não
probatório ("o dinheiro entrou"). O parser lê OFX 1.x (SGML) e 2.x (XML) sem
dependência nova, o import é idempotente por construção (um `insert` com
`unnest` + `on conflict`, não um laço de N) e a proveniência grava o **sha256
dos bytes recebidos** — sem isso, `origem='ofx'` seria uma palavra a mais na
digitação, pior que o lastro auto-declarado porque mentiria com aparência de
prova.

Um achado do caminho, com a premissa confirmada no próprio Postgres:
`Decimal('NaN')` é literal válido, `numeric` aceita, e o Postgres ordena `NaN`
como **maior que qualquer número** — `'NaN'::numeric > 0` e `>= 999999` são os
dois verdadeiros. Um `TRNAMT` com `NaN` atravessaria o `check (valor > 0)`,
cobriria **qualquer** parcela em `fn_baixar_parcela` e envenenaria toda soma da
carteira. Recusado na leitura do arquivo.

**Rotinas periódicas agendadas.** Régua de aging, varredura de atipicidade,
backup e restore-test rodavam só por clique — a data em que uma inadimplência
era declarada dependia de alguém lembrar. Agora um comando (`app/rotinas.py`),
uma agenda diária, e o que roda em cada dia decidido em código coberto por
teste. O restore-test não usa dia fixo (dia 31 pula cinco meses do ano): o
critério é *"esta competência já teve seu teste?"*, e o marcador só é escrito
após o sucesso.

**Memória de cálculo da apuração fiscal** (sem migration — tudo já estava
gravado). O contador recebia tributos apurados sem conseguir conferir a
derivação, numa linha que OC016 torna imutável: número sem derivação é número
que ninguém pode contestar nem corrigir. A memória é derivada do snapshot da
própria apuração, então a de um trimestre de 2021 sai igual daqui a cinco anos.

O detalhe que decide se a conferência serve para algo é o **arredondamento**:
verifiquei no banco que `0.125` vira `0,13` no Postgres e `0,12` com o padrão do
Python (`HALF_EVEN`). Sem `ROUND_HALF_UP`, toda apuração que caísse na metade
acusaria divergência falsa de um centavo — arruinando justamente o indicador que
precisa ser confiável.

**Vigilância das rotinas (migration 025, OC023).** Nenhuma execução era
registrada: o sistema não sabia o próprio estado e não conseguia dizer que o
último backup foi há nove dias. Agora há trilha append-only e aviso na tela, com
o relógio correndo desde o último **sucesso** — é o que pega a rotina que roda e
falha em silêncio, o caso perigoso, porque não há falha para ver. Limiares de
36h para as diárias (tolera uma execução perdida sem virar ruído) e 45 dias para
o restore-test mensal.

O que resta são **riscos residuais** (seção 6), que exigem integração ou decisão
externa, e a fila de configuração (seção 4).

---

## 3. Scorecard por domínio

Verde exige implementado, testado **e** sem achado confirmado em aberto.

| Domínio | Antes | Agora | Justificativa |
|---|---|---|---|
| **Capital e teto (Art. 5º)** | 🔴 | 🟢 | Três bordas fechadas (015), concorrência da versão vigente provada — mutação que remove o advisory lock reproduz a falha original 3 de 3 — e a hash-chain ancorada em chave monotônica (020), que também tornou impossível antedatar lançamento. |
| **Operações e novação** | 🟡 | 🟢 | Máquina de estados no trigger, novação atômica com prova de não-dupla-contagem, e agora testes HTTP das transições e do gate de liquidação. |
| **Cobrança** | 🔴 | 🟢 | Furo da liquidação fechado (017, OC022), `baixada` não contorna mais o lastro, a baixa tem autor, o lastro deixou de ser auto-declarado (024: o movimento vem de arquivo do banco com o sha256 dos bytes gravado) e **a tela de importação existe**, com o relatório que permite conferir que nenhuma linha do extrato se perdeu e a proveniência visível na lista. |
| **Contratos e registro** | 🟡 | 🟢 | O registro não nasce mais confirmado (021), o corpo cita o protocolo confirmado, e a emissão concorrente já era tratada. Sem defeito aberto — o que impede usar é externo: registradora contratada, assinatura eletrônica e dados da ESC. |
| **Fiscal (Lucro Presumido)** | 🔴 | 🟡 | Os quatro erros de conteúdo foram corrigidos e testados (018), e a apuração agora tem **memória de cálculo** derivada do snapshot da própria linha imutável — o contador confere a derivação tributo a tributo, e divergência entre recalculado e gravado aparece na tela. Continua amarelo por uma razão só, e ela não é minha: **`parametro_fiscal` está vazia**. A apuração recusa com OC015 até o contador informar presunção, alíquotas e regime — recusar em vez de assumir é o comportamento projetado, não defeito. |
| **Compliance PLD** | 🔴 | 🟢 | A evidência deixou de ser oca (bytes, hash no servidor, storage fail-closed, UI), a retenção conta do encerramento (022) e a detecção de atipicidade não depende mais de quando a varredura roda (023). Sem defeito aberto — o que falta é externo: parecer sobre o regime COAF, e agendar a varredura em vez de depender de clique. |
| **Segurança e auditoria** | 🔴 | 🟢 | Guarda fail-closed ativa (o serviço roda em `production` agora), `/docs` e `/openapi.json` fora do ar, `/metrics` em 401, rate limiting ligado, auditoria paginada. O serviço duplicado foi **removido**. |
| **Frontend** | 🔴 | 🟢 | `baseUrl` relativo provado no artefato (zero ocorrências de `localhost` no bundle), UI de identificação e de write-off, dicionário completo, retry preservando o corpo, feedback anunciado por `role="alert"`. 148 testes e 6 E2E. |
| **Qualidade e CI** | 🟡 | 🟢 | Falha dura sem banco (exit 4), teste de sincronia das três fontes de schema, piso de cobertura, docker build com smoke test, e a suíte de concorrência dentro do pytest. |
| **Infra e observabilidade** | 🔴 | 🟢 | `railway.json` versionado, health check em `/health/ready` provado no log, migrations em pré-deploy separado, logging emitindo, deploys rastreáveis por commit, as quatro rotinas agendadas e **verificadas em produção**, e agora a trilha `execucao_rotina` (025): o sistema sabe o próprio estado e avisa na tela quando uma rotina atrasa. O relógio corre desde o último **sucesso** — é o que pega a rotina que roda e falha em silêncio. |

---

## 4. O que falta, por dono

### Meu (código)

**Nada.** Os cinco defeitos que estavam nesta lista — hash-chain, registro
nascendo confirmado, protocolo no contrato, retenção e regra de atipicidade —
foram fechados; ver seção 2.

O que sobra do meu lado só existe como resposta a decisão sua: importação de
extrato (para o lastro deixar de ser auto-declarado), adaptador de registradora,
e notarização externa da hash-chain. Os três estão na seção 6 porque são
mudanças de escopo, não correções.

### Seu (configuração e decisão)

Já saíram da lista: cortar o acesso do serviço duplicado ao banco e removê-lo,
conferir a JWT Secret, ligar o modo produção, versionar o `railway.json`,
separar as migrations do start, e **agendar as quatro rotinas** — o serviço
`orgcred-rotinas` está de pé, com execução real verificada.

O que resta, em ordem:

1. **Bucket e `service_role` key do Supabase Storage.** Sem eles, arquivar
   identificação é recusado com 503 — e sem identificação arquivada nenhuma
   operação ativa (OC019). É o próximo bloqueio do fluxo primário.
2. **Habilitar o autodeploy do `orgcred-rotinas`** (Settings → Source → Enable).
   Hoje ele não reconstrói no push e pode executar código velho em silêncio —
   foi o que manteve o backup quebrado por duas rodadas depois de a correção já
   estar em produção.
3. **Escolher um canal de alerta** — e-mail, Slack, o que for. Deixou de ser
   pré-requisito: o sistema agora registra as execuções e mostra o atraso na
   tela. O canal serve para avisar quem **não está olhando a tela**, e é a
   última camada que falta.
4. **Dados reais da ESC e capital social.** Irreversível na prática: o primeiro
   contrato sela razão social e CNPJ num documento imutável (OC017), e a
   primeira apuração sela a base tributária (OC016). É o passo que finalmente
   destrava operar.

### Terceiros

8. Parâmetros fiscais do contador; entidade registradora contratada; parecer
   sobre PLD/COAF e IOF; assinatura eletrônica.

---

## 5. Veredito

**Ainda não dá para emprestar dinheiro** — mas o motivo mudou de natureza.

Três dias atrás o sistema estava inoperante e o teto do Art. 5º tinha duas
portas abertas alcançáveis por qualquer operador. Hoje as portas estão fechadas
e provadas por teste de mutação, a trilha de auditoria não acusa mais
adulteração falsa nem aceita lançamento antedatado, e a interface funciona de
ponta a ponta.

O que impede operar agora é **exclusivamente configuração e dado de negócio**.
Nenhum defeito de código do levantamento continua aberto, e as duas ausências
atacadas depois dele — lastro probatório e rotinas agendadas — estão fechadas
de ponta a ponta, backend e tela.

O **piloto fechado** que a Condição 1 destravou está disponível: sem capital
social carregado, sem parâmetro fiscal, poucos operadores, nenhuma operação
real. Valida deploy, login, observabilidade e fluxo de tela sem risco legal,
porque o sistema recusa operar sem os dados de negócio — e agora recusa também
subir mal configurado.

---

## 6. Riscos residuais

Continuam verdadeiros mesmo com todo o plano executado:

- **Os bytes do extrato não são arquivados — só o hash deles.** A importação
  OFX (024) tirou o lastro de auto-declarado e grava o sha256 do arquivo
  recebido, mas o OFX em si fica fora do sistema. Guardar os bytes (como já se
  faz com a evidência de identificação, migration 019) fecharia o ciclo
  probatório, e exige bucket próprio e política de retenção decidida.
- **O formulário manual continua existindo** ao lado da importação, e é o
  caminho que aceita data, valor e documento arbitrários. Ele é necessário
  (nem todo crédito chega por OFX), mas quem auditar precisa saber distinguir:
  a coluna de proveniência responde isso, e a tela precisa mostrá-la.
- **O gate OC004 prova que alguém digitou um protocolo**, não que houve
  registro em entidade registradora.
- **Conciliação errada é permanente** — não há estorno, e o remédio que a
  própria migration prescreve é impossível de registrar porque
  `movimento_bancario` tem `check (valor > 0)`.
- **Pagamento parcial não tem representação** no modelo.
- **A hash-chain é evidência, não fonte de verdade:** detecta adulteração de
  linha existente, não fabricação.
- **Nenhum alerta ativo.** A detecção de incidente depende de alguém abrir o
  painel.
- **A imagem de produção ignora o `uv.lock`** — o conjunto testado não é
  necessariamente o que roda.

---

## 7. Fluxo de branches e deploy

Uma branch só: **`main`** — default do GitHub, de trabalho e observada pelo
Railway. `master` foi apagada em 2026-08-11; não recriar.

O gatilho do GitHub **funciona**, mas está ligado ao serviço duplicado. Os
deploys do serviço real sobem por tarball local e têm hash de commit `-`.
Enquanto isso não for corrigido, publicar exige árvore limpa e sincronizada
com `origin/main` antes de empacotar.

**Rodar a suíte:** use `127.0.0.1`, não `localhost` — nesta máquina o
`localhost` resolve por `::1` primeiro e cada conexão custa 21 segundos de
timeout (148s contra 27s na suíte inteira).
