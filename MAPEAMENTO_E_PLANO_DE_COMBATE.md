# OrgCred — Mapeamento, scorecard e plano de entrada em produção

> **Levantamento independente de 2026-08-18.** 41 agentes sobre 11 domínios,
> com rodada adversarial: todo achado grave passou por um cético encarregado de
> **refutá-lo**. **22 sobreviveram** — 2 críticos, 9 altos, 10 médios, 1 baixo.
>
> **Atualizado em 2026-08-27 por uma verificação domínio a domínio** — onze
> céticos, um por domínio, obrigados a MEDIR contra Postgres e a tentar derrubar
> a nota que este documento dava. Seis notas caíram. A mais importante: a
> migration 027, que fechara três altos de cobrança na véspera e fora verificada
> e dada por verde, **tinha aberto um crítico** — e ele só apareceu porque um
> crítico de completude olhou a JUNTA entre dois domínios que haviam sido
> declarados verdes separadamente.
>
> Esse crítico está fechado pela 028, reproduzido nos dois sentidos. O restante
> das quedas — apuração fabricável por INSERT, instrumento contratual
> substituível por INSERT, a regra de fracionamento do PLD ancorada em
> `current_date` — segue aberto e está na seção 5.
>
> **A lição, que já é a terceira vez:** a verificação que fecha um furo não vê o
> furo que ela abre. A 027 perguntou "mesmo FITID em contas DIFERENTES entra?" e
> comemorou o sim; nunca perguntou "e quando é a MESMA conta escrita de dois
> jeitos?".
>
> Os agentes foram instruídos a **não** ler a versão anterior deste documento
> como verdade, e sim a olhar o código. Foi a decisão mais produtiva do
> levantamento: a seção 4 existe por causa dela.

---

## 0. Leia isto primeiro

**O teto do Art. 5º tem uma saída livre, alcançável pela API com papel de
operador.** Reproduzido ao vivo contra Postgres — por dois levantamentos
independentes e por mim:

```
capital social ............................. R$ 50.000
operação de R$ 30.000 ativa ................ comprometido: 30.000
   (12 parcelas em aberto, zero centavo comprovado)
renegociar com valor_principal = R$ 0,01 ... comprometido: 0
cancelar a substituta ...................... comprometido: 0
nova operação de R$ 50.000 ativa ........... comprometido: 50.000

R$ 80.000 na rua sobre R$ 50.000 de capital integralizado.
ledger: ativacao_operacao, renegociacao, ativacao_operacao
```

`fn_novar_operacao` aceita `valor_principal` arbitrário e não o confronta com
nada. É **o mesmo efeito que a migration 017 recusa em uma linha do próprio
cabeçalho** — *"liberar teto por um empréstimo que nunca foi pago permitiria
emprestar de novo o mesmo dinheiro que já se perdeu"* — reaberto pela porta
vizinha: o gate OC022 só olha `new.status = 'liquidada'`, e `renegociada` ficou
fora do conjunto que ocupa o teto.

O agravante não é o furo, é a rede. **A suíte de 570 testes passa verde por cima
dele e afirma o comportamento como correto** — `test_capital_engine.py:972`
renegocia 40.000 para 25.000 e assere `comprometido == 0` — e não existe um
único teste do endpoint de renegociação.

**FECHADO** pela migration 026 (OC024), em 2026-08-18. A regra: o comprometido
não pode diminuir numa novação sem lastro — a substituta tem que cobrir o saldo
devedor da original, calculado sobre `valor_amortizacao` e não sobre o valor
cheio da parcela (usar o valor cheio creditaria juros pagos como devolução de
principal, afrouxando o gate na direção do furo).

Verificado por reprodução: a sequência acima é recusada e o comprometido segue
em 30.000. Renegociação legítima preservada — alongar prazo, capitalizar juros e
reduzir na medida do que foi pago continuam passando.

**Quatro testes endossavam o furo**, não um. Todos reescritos para a nova
realidade; nenhum apagado, porque apagar esconderia que o comportamento mudou.

---

## 1. Retrato em uma frase

O sistema tem invariantes legais genuinamente bem construídos no banco e uma
rede de testes acima da média — e um histórico, agora em três repetições, de
**fechar um furo e abrir outro na mesma verificação**. O teto do Art. 5º está
defendido nos dois lados desde a 028 (no comprometido, pela 026; no lastro,
pela identidade da conta), mas o que resta aberto não é pequeno: duas tabelas
que deviam ser append-only aceitam INSERT que troca o registro vigente, e a
única regra de PLD de severidade alta não enxerga fato de mais de um dia.

---

## 2. Scorecard por domínio — pontuação

> **Regenerado em 2026-08-28**, depois dos consertos desta sessão (migrations
> 027–032, o portal do tomador, e o ataque aos findings de código de Infra,
> Rotinas, Segurança e Frontend). Os achados que sustentam cada nota estão na
> seção 3; aqui é a pontuação, com a rubrica ao lado para os números serem
> **reproduzíveis** na próxima rodada.

### A rubrica (auditável)

Cada domínio parte de 100 em dois eixos independentes. Penalidade por achado
aberto = gravidade (**crítico 40 · alto 20 · médio 8 · baixo 3**), no eixo do
seu dono:

- **Código** — defeito de implementação (dono = código). Mede: construído,
  testado, sem defeito aberto?
- **Prontidão** — bloqueio de operação (dono = dado / configuração / terceiro).
  Mede: pode entrar em produção?
- **Geral** = 0,6 × Código + 0,4 × Prontidão. Banda: 🟢 ≥ 90 · 🟡 70–89 · 🔴 < 70.

Os dois eixos existem porque a lição central deste projeto é que **o código dos
motores legais está são; o que impede produção é dado, configuração e terceiro**.
Um número só esconderia isso.

### A tabela

| Domínio | Código | Prontidão | Geral | Por quê |
|---|---:|---:|---:|---|
| Operações e novação | 100 | 100 | **100** 🟢 | Furo do Art. 5º fechado dos dois lados (026); sem achado aberto. |
| Cobrança e extrato | 100 | 100 | **100** 🟢 | Identidade `(documento_chave, valor, data)`; paridade Unicode fechada (032). |
| Fiscal (Lucro Presumido) | 100 | 97 | **99** 🟢 | Núcleo estável desde a 018; salto de versão da apuração **fechado** (033, OC016); apuração inconsistente é denunciada pela memória de cálculo. Só o footgun do skip local. |
| Portal do tomador | 97 | 100 | **98** 🟢 | Isolamento provado (12 testes + smoke); falta E2E da tela. |
| Frontend | 97 | 100 | **98** 🟢 | Contrato de erro agora DERIVA do `PGCODE_MAP` (não mais lista estática). |
| Contratos e registro | 97 | 97 | **97** 🟢 | Salto de versão que forjava o instrumento vigente **fechado** (033, OC017); resíduo de forja na próxima versão é §7. `enviado_em` antedatável; registradora não contratada. |
| Segurança e auditoria | 100 | 92 | **97** 🟢 | JWT exige `exp` e verifica emissor; rate limit global é config. |
| Qualidade e CI | 97 | 97 | **97** 🟢 | Ciclo alembic up/down provado; escopo CircleCI não observado daqui. |
| Capital e teto (Art. 5º) | 100 | 89 | **96** 🟢 | Código impecável; **capital social não integralizado** (teto R$ 0). |
| Infra e deploy | 97 | 92 | **95** 🟢 | Smoke da CI passou a **provar migration**; docs corrigidas. |
| Compliance PLD | 100 | 66 | **86** 🟡 | Código 100; **COAF** (terceiro) e **storage real** (config) faltam. |
| Rotinas e observabilidade | 97 | 77 | **89** 🟡 | Código testado; **cron de prod pré-025**, trilha vazia, backup sem volume. |

**Média da carteira: 96 / 100.** Placar por banda: **10 🟢 · 2 🟡 · 0 🔴.** Contra
os nove-verdes-com-dois-críticos de 18/08, é a honestidade funcionando: nenhum
crítico de código sobrou nos motores, e os dois 🟡 têm o eixo Código no teto — o
que os segura é externo (parecer de COAF, service_role key, deploy do cron).

**Achado desta sessão que a pontuação incorpora:** um forge por SQL direto (INSERT
de versão 99 vira o vigente) em contrato e apuração — que este mapeamento não
tinha encontrado — foi **fechado no vetor reproduzido** pela migration 033
(monotonia de versão). O resíduo (forja na próxima versão; apuração inconsistente)
está no §7 e no §3, e é por isso que Contratos/Fiscal seguem 🟢 sem esconder nada:
o que o banco PODE decidir, decide; o que não pode, está nomeado.

**Notas sobre a pontuação, para ela não ser lida como precisão que não tem:**
a Prontidão do Portal (100) é NOMINAL — o módulo nunca operou em produção (que
segue em 0026); o 100 diz "sem bloqueio conhecido", não "provado em produção". E
Capital/Fiscal/PLD dependem de **dado de negócio** (capital social,
`parametro_fiscal`) cuja ausência é recusa deliberada e correta — pesa na
Prontidão, não é defeito.

---

## 3. Achados confirmados

### Críticos

| Achado | Onde |
|---|---|
| A renegociação libera o teto integral sem prova de pagamento | [operacoes.py:522](app/routers/operacoes.py:522) |
| Novação devolve capital ao teto sem prova — a porta dos fundos do OC022 | [006:254](migrations/006_novacao_e_inadimplencia.sql:254) |

### Altos

| Achado | Onde | Situação |
|---|---|---|
| Janela ilimitada entre a baixa da original e a ativação da substituta | [006:262](migrations/006_novacao_e_inadimplencia.sql:262) | ✅ 026 |
| A autoria da baixa nunca é gravada pelo único caminho de produção | [cobranca.py:476](app/routers/cobranca.py:476) | ✅ router |
| `INSERT` em `parcela` sem guarda nenhuma — a agenda emitida aceita apêndice | [007:75](migrations/007_agenda_de_parcelas.sql:75) | ✅ 027 (OC025) |
| `UPDATE` direto baixa parcela sem cobertura de valor | [016:204](migrations/016_bordas_da_cobranca.sql:204) | ✅ 027 (OC011) |
| FITID colidindo entre contas descarta crédito real e o relatório fecha mesmo assim | [009:39](migrations/009_baixa_de_recebimento.sql:39) | ✅ 027 |
| Produção sem storage: arquivar responde 503 e OC019 trava todo tomador novo | [config.py:91](app/core/config.py:91) | 🔴 aberto |
| Rate limit é um balde único global atrás do proxy | [main.py:196](app/main.py:196) | 🔴 aberto |
| O cron não reconstrói no push — a trilha 025 pode não existir em produção | [OPERACAO.md](docs/OPERACAO.md) | 🔴 aberto |

**Como os cinco foram verificados**, porque a forma importa mais que o número:
cada ataque foi rodado contra Postgres real com dado gravado pelos caminhos
reais — capital, tomador com evidência, registro confirmado, ativação emitindo a
agenda pelo trigger, baixa por `fn_baixar_parcela` — e depois **repetido contra o
schema anterior**, onde os quatro passam: apêndice aceito (13 parcelas num
contrato de 12), parcela de R$ 1.134,72 quitada contra R$ 0,01, `truncate
parcela` apagando a agenda inteira, e o crédito do segundo banco recusado por
`movimento_documento_unico`. Um teste que só se vê passar não distingue a guarda
que funciona da guarda que nunca foi alcançada.

Os dez médios cobrem: confirmar registro sem autor, excedente do crédito virando
mora tributável, a tela mostrando o piso de retenção, `.env.example` prescrevendo
`localhost`, backup sem cópia externa, o smoke do CI que parou de provar
migrations, deploy que falha no health check deixando o schema já migrado, e a
ausência de alerta ativo.

---

## 4. Divergências entre a documentação e o código

**Esta é a seção mais importante do levantamento**, e ela existe porque os
agentes foram proibidos de tomar a documentação como verdade.

A versão anterior deste documento respondia **"Nada."** à pergunta *"o que falta,
de código"*. Havia dois críticos e nove altos em aberto. É a frase que autoriza
alguém a tratar o resto da lista como puramente operacional — e fui eu que a
escrevi.

Outras afirmações que o código não sustenta:

- **"Capital e teto 🟢"** — cada metade da justificativa era verdadeira
  isoladamente; o conjunto, não.
- **"a baixa tem autor"** — era NULL em **100%** das baixas feitas pela API.
  Verificado pelo endpoint HTTP, que devolveu 204 com a coluna vazia. **Hoje é
  verdade**: o router passa `usuario_id`, e o teste que prova isso passa pelo
  HTTP e compara a coluna com o id do usuário autenticado. O detalhe que
  explica como isso durou tanto: o teste da função de serviço já existia e
  passava verde o tempo todo — ele provava que a função grava quem recebe, nunca
  que alguém entrega.
- **"o relatório permite conferir que nenhuma linha do extrato se perdeu"** —
  falhava exatamente no caso em que mais importa: com FITID colidindo entre
  contas, a aritmética fechava **enquanto a linha se perdia**. **Hoje é
  verdade**, e o conserto teve de ser dos dois lados: a chave do banco e a
  deduplicação dentro do arquivo. Só o banco deixaria de pé o OFX com dois
  statements, cuja segunda linha morreria em Python como `repetidos_no_arquivo`.
- **"deploys rastreáveis por commit"** e **"rotinas verificadas em produção"** —
  o serviço de cron está sete commits atrás, e a tabela que a mesma linha celebra
  pode nem existir lá.
- **"rate limiting ligado"** — ligado, e inútil como isolamento.
- **A hash-chain "detecta adulteração mesmo com acesso direto ao banco"**
  ([005:13](migrations/005_ledger_imutavel.sql:13)) — não há um único `grant`,
  `revoke` ou RLS em nenhuma das 25 migrations. E a cadeia detecta adulteração
  **retroativa**, não **append forjado**: um `INSERT` direto de uma liquidação de
  R$ 999.999 é aceito, e a verificação devolve zero quebras.

Mais oito divergências em docstrings que descrevem intenção como se fosse
implementação — inclusive uma dizendo que o código de saída serve "para o alerta
disparar", quando não existe alerta algum no repositório.

---

## 5. O que falta, por dono

### Meu (código), nesta ordem

1. ~~**Gate de valor na novação.**~~ **Feito** (026, OC024). Era o único item
   que precisava estar pronto **antes** de o capital social ser carregado.

0. ~~**A identidade da conta no extrato.**~~ **Feito** (028). Fechou o crítico
   que a 027 abriu — vinha antes de tudo, porque reabria o furo do teto sem
   exigir má-fé.
2. ~~**Três furos de cobrança.**~~ **Feito** (027): chave `(documento,
   conta_origem)` com `NULLS NOT DISTINCT`, guarda de `INSERT` em `parcela`
   (OC025) com o `TRUNCATE` fechado junto, e cobertura de valor no trigger
   (OC011).
3. ~~**`baixado_por`.**~~ **Feito** — uma linha no router, e um teste que passa
   pelo HTTP para provar que alguém a executa.
4. **`INSERT` em `apuracao_fiscal` e em `contrato_emprestimo`.** As duas tabelas
   são append-only por trigger de UPDATE/DELETE e aceitam linha NOVA que troca o
   registro vigente: versão 99 numa e versão alta na outra, com hash que o
   próprio banco calcula e abençoa. `TRUNCATE` nas duas já foi fechado pela 028;
   falta o INSERT.
5. **A regra 1 do PLD ancorada em `current_date`** (023:188) — a única de
   severidade alta, e a que não enxerga fato de mais de um dia.
6. **Rate limit por cliente**, não um balde global — e por cliente REAL: hoje o
   slowapi chaveia pelo peer do proxy porque o uvicorn sobe sem
   `--forwarded-allow-ips`.
7. **O smoke do CI que não prova migration.** O job `alembic` deixou de ser
   vermelho por construção (uma linha na revisão 0006), mas o smoke continua
   afirmando provar o que um `select 1` não prova.
8. **Corrigir a documentação**, inclusive os docstrings que descrevem intenção
   como implementação — e as contagens relativas a HEAD, que envelhecem
   sozinhas ("sete commits atrás" já estava quatro números defasado quando foi
   reescrito).

**Dado a conferir antes de subir a 027**, e que ela deliberadamente não corrige
sozinha: baixas já gravadas contra movimento insuficiente. Só entram por SQL
direto (`fn_baixar_parcela` sempre recusou), a guarda nova é BEFORE ROW e não
revisita o que já está gravado, e reverter baixa é justamente o que este sistema
não faz. A consulta está no docstring do `upgrade()` da revisão 0027; havendo
linhas, a escolha entre reconciliar e encerrar por prejuízo é de negócio, não de
migration.

### Seu (configuração e decisão)

0. **A primeira linha em `usuario`**, com o UUID do usuário do Supabase Auth e
   papel `admin`. Medido em produção: a tabela tem **zero linhas**, não há
   endpoint de criação, e `get_current_user` responde 403 a quem não está lá —
   então, mesmo com o Supabase configurado e o login funcionando, **ninguém
   entra**. Está no `DECISOES_PENDENTES.md` desde julho e tinha se perdido no
   caminho para este plano; é o bloqueio mais barato de resolver e o único que
   impede até de olhar o sistema.
1. **Bucket e `service_role` key do Storage** — sem eles, nenhum tomador novo
   recebe crédito.
2. **Habilitar o autodeploy do `orgcred-rotinas`** — o cron está sete commits
   atrás.
3. **Destino de backup fora do provedor** — hoje dump e banco moram no mesmo
   projeto Railway.
4. **Canal de alerta.**
5. **Capital social e parâmetros fiscais** — por último, e só depois do item 1 da
   minha lista.

### Terceiros

Entidade registradora contratada, assinatura eletrônica, parecer sobre PLD/COAF e
IOF, parâmetros do contador.

---

## 6. Veredito

**Não dá para entrar em produção com dinheiro real.** Não há mais crítico
aberto, mas há altos — e o histórico deste documento recomenda desconfiança da
própria frase anterior: *"não há mais defeito de código no que a lei exige"* foi
escrita em 27/08 e derrubada no mesmo dia. É a terceira vez que o documento
afirma estar fechado o que não está, e a repetição é o próprio achado: **a
verificação que fecha um furo não vê o furo que ela abre.** O que quebrou o
ciclo desta vez não foi mais rigor dentro de cada domínio — foi um revisor
olhando a JUNTA entre dois domínios que tinham sido declarados verdes
separadamente.

O sistema está impedido por três razões distintas, e não confundi-las é o que
torna a fila acionável:

1. **Defeitos de código abertos, nenhum deles crítico.** A duplicação de lastro
   por grafia de conta — aberta pela 027, fechada pela metade pela 028 — está
   fechada pela **029**, que tira a conta da identidade e fecha a classe
   inteira. Junto, o alto da agenda do título extinto (OC026), agora com o
   `for share` que faltava para o gate sobreviver à concorrência. Seguem
   abertos, todos altos: `INSERT` que troca o instrumento
   contratual vigente, `INSERT` que troca a apuração fiscal vigente, a regra 1
   do PLD ancorada em `current_date`, e o rate limit global. Produção roda o
   schema **0026** e nada disto está no ar.
2. **Credencial ausente** — sem a `service_role` key, arquivar identificação
   responde 503; como OC019 exige evidência para ativar, nenhum tomador novo
   recebe crédito. É fail-closed correto **pelo motivo errado**: recusa por
   configuração faltante, não por decisão, e sem guarda de startup.
3. **Dados de negócio que faltam** — capital social e `parametro_fiscal`. Essa
   recusa é deliberada, testada e correta, e não conta contra ninguém.

---

## 7. Riscos residuais

- **A hash-chain é evidência contra adulteração retroativa, não contra
  fabricação.** Um `INSERT` forjado no ledger recebe hash válido.
- **Não há isolamento de privilégio no banco.** A aplicação é dona das tabelas, e
  os comentários que afirmam o contrário estão errados. Instância concreta,
  medida nesta sessão: um `INSERT` por SQL direto na PRÓXIMA versão de
  `contrato_emprestimo` (corpo gerado pela app, que o banco não re-deriva) ou de
  `apuracao_fiscal` (números inventados) ainda fabrica um vigente. A 033 fechou
  o SALTO de versão; a monotonia é o que o banco pode; o resto é este item. A
  apuração inconsistente é, além disso, denunciada pela memória de cálculo.
- **Os bytes do extrato não são arquivados** — só o hash.
- **O gate OC004 prova que alguém digitou um protocolo**, não que houve registro.
- **Backup e banco no mesmo provedor.**
- **Nenhum alerta ativo** — toda a observabilidade é pull e exige credencial.
