# OrgCred — Mapeamento, scorecard e plano de entrada em produção

> Revisado em **2026-08-13**, depois da execução da Condição 1 e da Condição 2.
> O levantamento base é de 2026-08-12: 53 agentes sobre 10 domínios, com rodada
> adversarial — todo achado grave passou por um cético encarregado de refutá-lo,
> e **32 sobreviveram**. Este documento marca quais deles foram fechados e
> quais continuam abertos.

---

## 0. Leia isto primeiro

**A exposição do serviço duplicado continua viva.** O serviço Railway `OrgCred`
(`eaa4e36a-594b-4f24-ab00-1927b8c52e65`) tem a `ORGCRED_DATABASE_URL` do
Postgres de produção e não tem `ORGCRED_SUPABASE_JWT_SECRET`. Nada do que foi
feito no código muda isso — é configuração, e está no seu balde.

**Mudou uma coisa importante desde ontem:** a guarda fail-closed agora **recusa
iniciar** em produção com a JWT secret no default. Ou seja, no próximo deploy
esse serviço não sobe mais em modo inseguro — ele falha, ruidosamente. E o
`orgcred-api` também não subirá se a secret configurada nele não for a real.

---

## 1. Retrato em uma frase

O sistema deixou de estar inoperante e passou a defender o teto do Art. 5º
pelas bordas, não só pela porta da frente — mas continua **não operável**, por
falta de dados de negócio e configuração, e carrega dois defeitos conhecidos
que não foram fechados.

---

## 2. O que mudou em 2026-08-12/13

| | Antes | Agora |
|---|---|---|
| Testes backend | 198 | **355** |
| Cobertura | 92% | **93%** (piso de 85% ativo na CI) |
| Testes frontend | 50 | **148** |
| E2E | 5 (todos quebrados) | **6, verdes** |
| Migrations | 14 | **19** |
| SQLSTATEs no banco | 18 | **21** |
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

### Não fechado, e são defeitos conhecidos

| Achado | Onde | Por que ainda está aberto |
|---|---|---|
| **Hash-chain ordena por `created_at = now()`** → acusa adulteração falsa sob concorrência | [005:53](migrations/005_ledger_imutavel.sql:53) e [005:107](migrations/005_ledger_imutavel.sql:107) | Não entrou em nenhum passo do plano. Exige trocar a ordenação por chave monotônica e reindexar a verificação. **É o defeito aberto mais grave**: destrói o valor probatório da trilha justamente quando ela é acionada. |
| `registro_operacao` pode **nascer** `confirmado` | [012:159](migrations/012_contrato_e_registro.sql:159) | O trigger é `before update or delete`, não cobre `INSERT`. A própria suíte depende desse buraco para montar cenário. |
| O contrato imprime `registro_entidade_ref` (texto livre) em vez do protocolo confirmado | [contrato.py:128](app/contrato.py:128) | Conteúdo do instrumento, não invariante — mas é o documento que vai a terceiros. |
| Retenção ancorada na data de **arquivamento**, não no encerramento da operação | [010:44](migrations/010_compliance_interno.sql:44) | Para um contrato de 60 parcelas, o prazo legal vence junto com o contrato — ~5 anos antes do que o art. 10 III exige. |

---

## 3. Scorecard por domínio

Verde exige implementado, testado **e** sem achado confirmado em aberto.

| Domínio | Antes | Agora | Justificativa |
|---|---|---|---|
| **Capital e teto (Art. 5º)** | 🔴 | 🟡 | As três bordas foram fechadas (015) e a concorrência da versão vigente está provada — mutação que remove o advisory lock reproduz a falha original 3 de 3. Não é verde por causa da hash-chain ordenada por `now()`. |
| **Operações e novação** | 🟡 | 🟢 | Máquina de estados no trigger, novação atômica com prova de não-dupla-contagem, e agora testes HTTP das transições e do gate de liquidação. |
| **Cobrança** | 🔴 | 🟡 | O furo crítico da liquidação está fechado (017, OC022), `baixada` não contorna mais o lastro, a baixa tem autor. Não é verde porque o lastro continua **auto-declarado**: não há importação de extrato. |
| **Contratos e registro** | 🟡 | 🟡 | Sem mudança. O hash é calculado pelo banco e o gate OC004 está provado, mas o registro pode nascer confirmado e o corpo imprime texto livre. Bloqueadores reais são externos. |
| **Fiscal (Lucro Presumido)** | 🔴 | 🟡 | Os quatro erros de conteúdo foram corrigidos e testados (018). Não é verde porque nenhum parâmetro real existe — a apuração é recusada por OC015, de propósito, até o contador informar. |
| **Compliance PLD** | 🔴 | 🟡 | A evidência deixou de ser oca: bytes de verdade, hash no servidor, storage com fail-closed, e UI de arquivamento e verificação. Não é verde pela retenção mal ancorada e pelo regime COAF pendente de parecer. |
| **Segurança e auditoria** | 🔴 | 🟡 | Guarda fail-closed de configuração, `/docs` desligado em produção, `/metrics` protegido, rate limiting de fato ligado, auditoria paginada com teto de página. Não é verde enquanto o serviço duplicado existir. |
| **Frontend** | 🔴 | 🟢 | `baseUrl` relativo provado no artefato (zero ocorrências de `localhost` no bundle), UI de identificação e de write-off, dicionário completo, retry preservando o corpo, feedback anunciado por `role="alert"`. 148 testes e 6 E2E. |
| **Qualidade e CI** | 🟡 | 🟢 | Falha dura sem banco (exit 4), teste de sincronia das três fontes de schema, piso de cobertura, docker build com smoke test, e a suíte de concorrência dentro do pytest. |
| **Infra e observabilidade** | 🔴 | 🔴 | O logging passou a emitir, mas o serviço duplicado segue vivo, as migrations continuam no `CMD`, o health check aponta para `/health` e não `/health/ready`, não há `railway.json` versionado nem alvo de rollback. |

---

## 4. O que falta, por dono

### Meu (código)

1. **Hash-chain por chave monotônica** — o defeito aberto mais grave.
2. `registro_operacao` nascendo confirmado (trigger `BEFORE INSERT`).
3. Corpo do contrato imprimindo o protocolo confirmado.
4. Retenção ancorada no encerramento da operação.

### Seu (configuração e decisão)

1. **Cortar a `ORGCRED_DATABASE_URL` do serviço duplicado** — reversível, e é
   a exposição viva.
2. **Conferir a JWT Secret** no painel do Supabase. Agora é pré-requisito de
   deploy: sem ela correta, a aplicação recusa iniciar.
3. **Bucket e `service_role` key** do Supabase Storage — sem eles, arquivar
   identificação é recusado, e sem identificação nenhuma operação ativa.
4. **`railway.json` versionado, migrations fora do `CMD`, gatilho no serviço
   certo**, health check em `/health/ready`.
5. **Remover o serviço duplicado** (irreversível — por último).
6. **Agendar** backup, restore test, régua de aging e varredura de atipicidade.
7. **Dados reais da ESC e capital social** (irreversível na prática: o primeiro
   contrato sela razão social e CNPJ num documento imutável por OC017).

### Terceiros

8. Parâmetros fiscais do contador; entidade registradora contratada; parecer
   sobre PLD/COAF e IOF; assinatura eletrônica.

---

## 5. Veredito

**Ainda não dá para emprestar dinheiro** — mas o motivo mudou de natureza.

Ontem o sistema estava inoperante e o teto do Art. 5º tinha duas portas
abertas alcançáveis por qualquer operador. Hoje as portas estão fechadas e
provadas por teste de mutação, e a interface funciona de ponta a ponta.

O que impede operar agora é **configuração e dado de negócio**, mais quatro
defeitos conhecidos que eu ainda não fechei — nenhum deles alcançável pela
API, mas o da hash-chain compromete a trilha de auditoria sob concorrência, e
é o próximo da fila.

O **piloto fechado** que a Condição 1 destravou está disponível: sem capital
social carregado, sem parâmetro fiscal, poucos operadores, nenhuma operação
real. Valida deploy, login, observabilidade e fluxo de tela sem risco legal,
porque o sistema recusa operar sem os dados de negócio — e agora recusa também
subir mal configurado.

---

## 6. Riscos residuais

Continuam verdadeiros mesmo com todo o plano executado:

- **O lastro bancário é auto-declarado.** Não existe importação de extrato: o
  único produtor de `movimento_bancario` é um formulário manual. O invariante
  entregue é estrutural ("existe um registro apontado"), não probatório ("o
  dinheiro entrou").
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
