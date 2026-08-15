# OrgCred — Mapeamento, scorecard e plano de entrada em produção

> Revisado em **2026-08-15**, com **todos os defeitos de código do
> levantamento fechados**.
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

**Mitigação parcial que já existe:** a guarda fail-closed **recusa iniciar** em
produção com a JWT secret no default. No próximo deploy esse serviço não sobe
mais em modo inseguro — ele falha, ruidosamente. O `orgcred-api` também não
subirá se a secret configurada nele não for a real.

---

## 1. Retrato em uma frase

Todos os defeitos de código que o levantamento encontrou estão fechados: o teto
do Art. 5º é defendido pelas bordas, a trilha de auditoria não acusa mais
adulteração falsa nem aceita lançamento antedatado, e a interface funciona de
ponta a ponta. O que impede operar é **configuração e dado de negócio** — mais
riscos residuais que exigem integração externa, não código.

---

## 2. O que mudou em 2026-08-12/15

| | Antes | Agora |
|---|---|---|
| Testes backend | 198 | **405** |
| Cobertura | 92% | **93,2%** (piso de 85% ativo na CI) |
| Testes frontend | 50 | **148** |
| E2E | 5 (todos quebrados) | **6, verdes** |
| Migrations | 14 | **23** |
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

O que resta são **riscos residuais** (seção 6), que exigem integração ou decisão
externa, e a fila de configuração (seção 4).

---

## 3. Scorecard por domínio

Verde exige implementado, testado **e** sem achado confirmado em aberto.

| Domínio | Antes | Agora | Justificativa |
|---|---|---|---|
| **Capital e teto (Art. 5º)** | 🔴 | 🟢 | Três bordas fechadas (015), concorrência da versão vigente provada — mutação que remove o advisory lock reproduz a falha original 3 de 3 — e a hash-chain ancorada em chave monotônica (020), que também tornou impossível antedatar lançamento. |
| **Operações e novação** | 🟡 | 🟢 | Máquina de estados no trigger, novação atômica com prova de não-dupla-contagem, e agora testes HTTP das transições e do gate de liquidação. |
| **Cobrança** | 🔴 | 🟡 | O furo crítico da liquidação está fechado (017, OC022), `baixada` não contorna mais o lastro, a baixa tem autor. Não é verde porque o lastro continua **auto-declarado**: não há importação de extrato. |
| **Contratos e registro** | 🟡 | 🟢 | O registro não nasce mais confirmado (021), o corpo cita o protocolo confirmado, e a emissão concorrente já era tratada. Sem defeito aberto — o que impede usar é externo: registradora contratada, assinatura eletrônica e dados da ESC. |
| **Fiscal (Lucro Presumido)** | 🔴 | 🟡 | Os quatro erros de conteúdo foram corrigidos e testados (018). Não é verde porque nenhum parâmetro real existe — a apuração é recusada por OC015, de propósito, até o contador informar. |
| **Compliance PLD** | 🔴 | 🟢 | A evidência deixou de ser oca (bytes, hash no servidor, storage fail-closed, UI), a retenção conta do encerramento (022) e a detecção de atipicidade não depende mais de quando a varredura roda (023). Sem defeito aberto — o que falta é externo: parecer sobre o regime COAF, e agendar a varredura em vez de depender de clique. |
| **Segurança e auditoria** | 🔴 | 🟡 | Guarda fail-closed de configuração, `/docs` desligado em produção, `/metrics` protegido, rate limiting de fato ligado, auditoria paginada com teto de página. Não é verde enquanto o serviço duplicado existir. |
| **Frontend** | 🔴 | 🟢 | `baseUrl` relativo provado no artefato (zero ocorrências de `localhost` no bundle), UI de identificação e de write-off, dicionário completo, retry preservando o corpo, feedback anunciado por `role="alert"`. 148 testes e 6 E2E. |
| **Qualidade e CI** | 🟡 | 🟢 | Falha dura sem banco (exit 4), teste de sincronia das três fontes de schema, piso de cobertura, docker build com smoke test, e a suíte de concorrência dentro do pytest. |
| **Infra e observabilidade** | 🔴 | 🔴 | O logging passou a emitir, mas o serviço duplicado segue vivo, as migrations continuam no `CMD`, o health check aponta para `/health` e não `/health/ready`, não há `railway.json` versionado nem alvo de rollback. |

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

Três dias atrás o sistema estava inoperante e o teto do Art. 5º tinha duas
portas abertas alcançáveis por qualquer operador. Hoje as portas estão fechadas
e provadas por teste de mutação, a trilha de auditoria não acusa mais
adulteração falsa nem aceita lançamento antedatado, e a interface funciona de
ponta a ponta.

O que impede operar agora é **exclusivamente configuração e dado de negócio**.
Nenhum defeito de código do levantamento continua aberto.

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
