# OrgCred — Mapeamento, scorecard e plano de entrada em produção

> Levantamento de **2026-08-12**, feito por 53 agentes em paralelo sobre os 10
> domínios do sistema, com uma rodada adversarial: todo achado grave passou por
> um cético cuja tarefa era **refutá-lo**. Dos achados levantados, **32
> sobreviveram**. O que está aqui é o que resistiu a alguém tentando provar que
> estava errado.

---

## 0. Leia isto primeiro

**Existe uma exposição viva em produção neste momento.** O serviço Railway
`OrgCred` (`eaa4e36a-594b-4f24-ab00-1927b8c52e65`), criado por engano, está
`SUCCESS` com deployment ativo, tem a `ORGCRED_DATABASE_URL` do **Postgres de
produção** e **não tem** `ORGCRED_ENVIRONMENT` nem
`ORGCRED_SUPABASE_JWT_SECRET`. Sem elas ele cai nos defaults de
[config.py:25](app/core/config.py:25) — ou seja, roda como `development` com a
secret `dev-secret-key-change-in-prod`, **que está versionada no repositório**.

É uma segunda instância da aplicação inteira servindo o banco de produção,
aceitando JWT assinado com uma chave que qualquer pessoa lê no repo. O que a
segura hoje é apenas não ter domínio público — isso é topologia de rede, não
barreira de segurança, e está a um clique de `generate_domain`.

**Primeiro passo do plano, antes de qualquer outra coisa:** remover a
`ORGCRED_DATABASE_URL` desse serviço. É reversível.

**E o sistema está funcionalmente inoperante.** O bundle servido em produção
contém literalmente `setConfig({baseUrl:'http://localhost:8000'})`. O operador
autentica e nenhuma chamada de API funciona.

---

## 1. Retrato em uma frase

O OrgCred cumpre a promessa arquitetural que se propôs — **os invariantes legais
estão no banco, não no Python** — mas as bordas desse desenho estão abertas em
dois pontos que furam o teto do Art. 5º, e a instância em produção não funciona.

O que é sólido e vale dizer com a mesma clareza: os **18 SQLSTATEs da classe
OC** têm cada um ao menos um teste que assere o **código** e não a mensagem,
rodando contra Postgres real. A novação é atômica sob advisory lock, com teste
provando que original mais substituta não somam capital em dobro. A matemática
PRICE/SAC fecha exatamente. E a recusa por falta de dado de negócio — capital
social, alíquota, dados da ESC — é **deliberada, testada e correta**: é o
sistema se negando a inventar número com efeito jurídico.

---

## 2. Scorecard por domínio

Verde exige três coisas ao mesmo tempo: implementado, testado, e sem achado
confirmado em aberto.

| Domínio | Nota | Por quê |
|---|---|---|
| **Capital e teto (Art. 5º)** | 🔴 | Gates de transição sólidos sob advisory lock, ledger append-only com hash-chain. Mas as **bordas** estão abertas: `UPDATE` de `valor_principal` em operação já ativa não passa por gate nenhum; `esc_capital_social` só tem trigger de `INSERT`; `valor > 0` vive só no Pydantic. A hash-chain ordena por `created_at = now()`, o que produz **quebra falsa** sob concorrência — reproduzido em Postgres real. |
| **Operações e novação** | 🟡 | O domínio mais bem construído. Máquina de estados integralmente no trigger, novação atômica com teste provando que 40.000 + 25.000 não somam 65.000 de comprometido. Falta teste HTTP dos quatro endpoints de transição e prova de terminalidade dos estados finais. |
| **Cobrança** | 🔴 | Matemática correta e provada, aging derivado, baixa com lastro por trigger. Mas `POST /operacoes/{id}/liquidar` devolve **100% do capital ao teto sem uma parcela paga**. O status `baixada` atravessa todas as guardas. A baixa — único ato irreversível do ciclo — **não tem autor**. |
| **Contratos e registro** | 🟡 | Hash SHA-256 calculado pelo **banco**, instrumento imutável (OC017), gate OC004 provado nos quatro caminhos. Defeitos de conteúdo, não de arquitetura: `registro_operacao` pode **nascer** `confirmado` (o trigger é `before update or delete`), e o corpo do contrato imprime texto livre em vez do protocolo. Bloqueadores reais são externos. |
| **Fiscal (Lucro Presumido)** | 🔴 | Arquitetura certa, **conteúdo fiscal errado em quatro pontos**: apuração de período passado usa o parâmetro de hoje; competência soma as duas agendas após novação; caixa ancora na conciliação e não no crédito bancário; mora e multa são descartadas. Nenhum teste cobre esses caminhos. |
| **Compliance PLD** | 🔴 | Gate OC019 no lugar certo e provado, imutabilidade real. Mas a **evidência é oca**: o sha256 chega pronto do cliente, nenhum byte é lido pelo servidor, e **não existe storage**. A retenção ancora no arquivamento, não no encerramento — contraria o art. 10 III. |
| **Segurança e auditoria** | 🔴 | Zero-Trust real: papel e status vêm do banco a cada request, nunca do JWT. Derrubado pelo **serviço duplicado vivo**, pela ausência de guarda fail-closed de configuração, e por `/metrics`, `/docs` e `/openapi.json` públicos em produção. Rate limiting é código morto. |
| **Frontend** | 🔴 | Base boa: dicionário de erro por código com teste provando ausência de matching por substring, E2E real. Derrubado pelo **baseUrl `localhost:8000` no bundle de produção** e por **não existir tela** para arquivar a evidência que o gate OC019 exige. 6 das 13 telas sem teste. |
| **Qualidade e CI** | 🟡 | O ponto mais forte: 198 testes contra Postgres real, 92% de cobertura, os 18 SQLSTATEs cobertos por código. Defeitos de encanamento: sem banco de teste a suíte vira SKIP e **o pytest sai 0**; o job `integration` valida um trigger de 11 migrations atrás; a imagem Docker nunca é construída na CI. |
| **Infra e observabilidade** | 🔴 | O mais frágil. Serviço duplicado apontado ao banco. Migrations rodam no `CMD` do container, sem lock e sem fase de release. Health check aponta para `/health`, que não prova nada (`/health/ready` existe e não é usado). **O logging estruturado não emite nada** em produção. Nenhum alvo de rollback. |

---

## 3. Achados confirmados

32 sobreviveram à refutação. Os dois críticos e os treze altos:

### Crítico

| Achado | Onde |
|---|---|
| Liquidar a operação libera capital e mata a cobrança **sem nenhum lastro bancário** | [operacoes.py:427](app/routers/operacoes.py:427) |
| O bundle **em produção** aponta a API para `http://localhost:8000` | [client.ts:6](frontend/src/api/client.ts:6) |

### Alto

| Achado | Onde |
|---|---|
| `UPDATE` de `valor_principal` em operação ativa não passa por gate — teto furado sem rastro no ledger | [014:100](migrations/014_gate_identificacao.sql:100) |
| A hash-chain ordena por `created_at = now()` → **quebra falsa** sob concorrência | [005:51](migrations/005_ledger_imutavel.sql:51) |
| Status `baixada` contorna integralmente a amarra de lastro | [009:107](migrations/009_baixa_de_recebimento.sql:107) |
| A baixa de recebimento **não tem autor** em lugar nenhum | [009:165](migrations/009_baixa_de_recebimento.sql:165) |
| A agenda nunca é fechada na liquidação ou novação → juros contados em dobro | [011:176](migrations/011_apuracao_fiscal.sql:176) |
| Apuração de período passado usa o parâmetro vigente **hoje** | [011:158](migrations/011_apuracao_fiscal.sql:158) |
| Competência soma parcelas de operações renegociadas → receita tributada duas vezes | [011:174](migrations/011_apuracao_fiscal.sql:174) |
| Caixa usa a data da baixa no sistema, não a do crédito no extrato | [011:170](migrations/011_apuracao_fiscal.sql:170) |
| Mora e multa recebidas são descartadas — subdeclaração | [011:179](migrations/011_apuracao_fiscal.sql:179) |
| **Não existe storage**: o documento arquivado nunca é persistido | [models.py:137](app/models.py:137) |
| Gate OC019 ligado **sem nenhuma tela** para arquivar a evidência | [tomadores/$id.tsx:44](frontend/src/routes/_authenticated/tomadores/$id.tsx:44) |
| Serviço duplicado vivo, apontado ao banco de produção, com a JWT secret pública | [config.py:25](app/core/config.py:25) |

Os 17 médios cobrem: `esc_capital_social` sem trigger de `UPDATE`/`DELETE`, o
teste de concorrência pinado no schema 003 e excluído do pytest, lastro
auto-declarado, `registro_operacao` nascendo confirmado, hash de identificação
informado pelo cliente, retenção sem CHECK, retry descartando o corpo da
requisição, 422 renderizado como `[object Object]`, suíte virando SKIP
silencioso, imagem Docker nunca construída na CI, e `/metrics` público.

---

## 4. Bloqueadores, por dono

O que separa esta seção da anterior: aqui não é defeito, é **quem consegue
resolver**.

### Resolve escrevendo código (agente)

1. Bundle apontando para `localhost:8000` — o sistema está inoperante por isso.
2. Gate OC019 ligado sem tela de arquivamento — fluxo primário bloqueado ponta a ponta.
3. Guarda fail-closed de configuração — recusar subir em produção com a secret default.
4. Logging que não emite nada — entrar em produção com dinheiro real e zero log é imprudente.
5. Uma pipeline verde que não prova que os invariantes rodaram.

### Depende de decisão sua

6. **Política de liquidação** — o que distingue quitação de write-off, e qual
   devolve capital ao teto. Não dá para codificar antes da regra existir: perdão
   de dívida é caso legítimo, e um gate ingênuo quebraria operação real.
7. **Dados da ESC e capital social** — sem eles o teto é R$ 0,00 e nada ativa.
   O sistema recusando é o comportamento projetado, não defeito.
8. **Entidade registradora** — 4 finalistas (CRDC, SPC Grafeno, CERC, B3),
   contato comercial não feito.
9. **Serviço duplicado e rastreabilidade do deploy** — infra, mas o acesso é seu.

### Depende de terceiro

10. **Parâmetros fiscais** do contador — presunção, alíquotas, regime.
11. **Parecer jurídico** sobre PLD/COAF aplicável a ESC e sobre IOF-crédito.
12. **Assinatura eletrônica** do instrumento e credencial do canal SISCOAF.

### Credencial

13. Confirmar que `ORGCRED_SUPABASE_JWT_SECRET` é a JWT Secret **real** do
    projeto Supabase. Se não for, todo token legítimo falha e ninguém entra.

---

## 5. Plano de entrada em produção

Ordenado por dependência, não por facilidade. Passos irreversíveis vêm depois
dos verificáveis.

### Condição 1 — sem isto não se discute nada

| # | Passo | Dono | Como verificar |
|---|---|---|---|
| 1 | **Cortar o acesso do serviço duplicado ao banco**: remover `ORGCRED_DATABASE_URL` de `eaa4e36a` e redeployar | você | `list_variables` não deve mais listar a variável; `get_logs` deve mostrar falha de conexão e **nenhuma** linha de `alembic.runtime.migration` |
| 2 | Confirmar que a JWT Secret configurada é a real do Supabase | você | Login real + `GET /api/me` → 200 com papel e nome |
| 3 | Guarda fail-closed: recusar iniciar em produção com secret default; corrigir `.env.example` | agente | `ORGCRED_ENVIRONMENT=production` + secret default → `ConfigError` |
| 4 | Corrigir o `baseUrl` do frontend para relativo | agente | `grep -c 'localhost:8000' dist/assets/*.js` → 0, e o dashboard carrega dados |
| 5 | Inicializar o logging da stdlib | agente | `app_startup` em JSON nos logs do deploy |

### Condição 2 — sem isto não se coloca dinheiro real

| # | Passo | Dono |
|---|---|---|
| 6 | Fechar as brechas do CI: sincronia das 3 fontes de schema, falha dura sem banco, docker build com smoke test | agente |
| 7 | Reescrever os testes de concorrência e de invariante para as 14 migrations, asserindo por SQLSTATE | agente |
| 8 | **Migration 015 — bordas do capital**: imutabilidade de `operacao_credito` ativa, `esc_capital_social` em `UPDATE`/`DELETE`, CHECKs de valor positivo | agente |
| 9 | **Migration 016 — bordas da cobrança e compliance**: `baixada`, `movimento_id`, `BEFORE TRUNCATE`, autoria da baixa | agente |
| 10 | **DECISÃO: política de liquidação** | você |
| 11 | **Migration 017 — gate de liquidação** implementando a política | agente |
| 12 | **UI de identificação** com storage real e hash calculado no servidor | agente |

### Condição 3 — sem isto não se apura tributo

| # | Passo | Dono |
|---|---|---|
| 13 | Correções fiscais: parâmetro por data do trimestre, filtro de operação viva, âncora no crédito bancário, mora e multa | agente |

### Condição 4 — encerramento

| # | Passo | Dono | Reversível |
|---|---|---|---|
| 14 | Hardening: `/metrics`, `/docs`, rate limiting, paginação da auditoria | agente | sim |
| 15 | `railway.json` versionado, migrations fora do `CMD`, gatilho no serviço certo | você | sim |
| 16 | **Remover o serviço duplicado** | você | **não** |
| 17 | Agendar backup, restore test, régua de aging e varredura de atipicidade | você | sim |
| 18 | **Carregar os dados reais**: `ORGCRED_ESC_*`, capital social, parâmetros fiscais | você | **não** |

O passo 18 é irreversível na prática: o primeiro contrato sela razão social e
CNPJ num documento imutável por OC017, e a primeira apuração sela a base
tributária por OC016.

---

## 6. Veredito

**Não dá para entrar em produção hoje** — e o motivo mais imediato não é
nenhum invariante legal, é que o sistema está funcionalmente inoperante e com
uma exposição viva.

Há um caminho intermediário honesto: com a **Condição 1** cumprida, dá para
subir em **piloto fechado** — sem capital social carregado, sem parâmetro
fiscal, com dois ou três operadores conhecidos e nenhuma operação real. Isso
valida deploy, login, observabilidade e fluxo de tela sem risco legal, porque o
próprio sistema recusa operar sem os dados de negócio.

O que não dá é chamar isso de produção e emprestar dinheiro. A **Condição 2** é
o divisor: antes dela, qualquer operação real corre sob um teto que o banco não
consegue defender por duas portas conhecidas.

---

## 7. Riscos residuais

Coisas que **continuam verdadeiras mesmo depois de todo o plano**, e que só se
fecham com decisão ou integração externa:

- **O lastro bancário continua auto-declarado.** Não existe importação de
  extrato: o único produtor de `movimento_bancario` é um formulário manual que
  aceita data, valor e documento arbitrários. O invariante entregue é
  estrutural ("existe um registro apontado"), não probatório ("o dinheiro
  entrou"). Para uma ESC cuja defesa em fiscalização é a rastreabilidade do
  fluxo financeiro, essa distinção importa.
- **O gate OC004 prova que alguém digitou um protocolo**, não que houve
  registro em entidade registradora.
- **Conciliação errada é permanente.** Não há estorno — decisão deliberada —
  mas o remédio que a própria migration prescreve (lançamento de correção) é
  impossível de registrar, porque `movimento_bancario` tem `check (valor > 0)`.
- **Pagamento parcial não tem representação** no modelo, e pagamento a maior
  consome o movimento sem registrar o excedente. Em carteira inadimplente, o
  painel superestima o vencido.
- **A hash-chain é evidência, não fonte de verdade.** Ela detecta adulteração
  de linha existente, não fabricação: um `INSERT` forjado receberia hash válido.
- **Nenhum alerta ativo.** Mesmo com o logging corrigido, a detecção de
  incidente depende de alguém abrir o painel.
- **A imagem de produção ignora o `uv.lock`.** O conjunto testado não é
  necessariamente o que roda — lacuna de cadeia de custódia num sistema com
  ledger hash-chained.
- **A retenção ancora na data de arquivamento**, não no encerramento da
  operação. Para um contrato de 60 parcelas, o prazo legal vence junto com o
  contrato, ~5 anos antes do que o art. 10 III exige.
- **Acessibilidade:** zero `role="alert"` ou `aria-live` no frontend. Um
  operador com leitor de tela confirma uma ativação, o banco recusa por OC001,
  e nada é anunciado.

---

## 8. Fluxo de branches e deploy

O repositório tem **uma branch só: `main`** — default do GitHub, de trabalho e
observada pelo Railway. `master` existiu em paralelo até 2026-08-11 e foi
apagada. Não recriar.

O gatilho de deploy do GitHub **funciona**, mas está ligado ao serviço
duplicado, não ao `orgcred-api`. Os 6 deploys do serviço real subiram por
tarball local e têm hash de commit `-`. Enquanto o passo 15 não for feito,
publicar depende de disciplina manual: árvore limpa e sincronizada com
`origin/main` antes de empacotar.
