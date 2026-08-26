# OrgCred — Mapeamento, scorecard e plano de entrada em produção

> **Levantamento independente de 2026-08-18.** 41 agentes sobre 11 domínios,
> com rodada adversarial: todo achado grave passou por um cético encarregado de
> **refutá-lo**. **22 sobreviveram** — 2 críticos, 9 altos, 10 médios, 1 baixo.
>
> **Os dois críticos foram fechados** pela migration 026 (OC024) e **cinco dos
> nove altos** pelas migrations 026 e 027 (OC025) mais uma linha no router —
> todos verificados por reprodução, e cada um também pela **contraprova**: os
> mesmos comandos rodados contra o schema anterior, onde passam. Uma guarda que
> nunca se viu deixar passar não foi verificada, foi assumida.
>
> Os altos que seguem abertos estão na seção 5, com dono.
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
rede de testes acima da média; o furo crítico do invariante central e os três
altos de cobrança **foram fechados e reproduzidos nos dois sentidos**, e o que
resta para produção é configuração, dado de negócio e um alto de segurança —
não mais um defeito no que a lei exige.

---

## 2. Scorecard por domínio

Verde exige implementado **e** testado **e** sem achado confirmado em aberto.

| Domínio | Nota | Por quê |
|---|---|---|
| **Capital e teto (Art. 5º)** | 🟢 | A saída pela novação foi **fechada e verificada** (026, OC024): reproduzi a sequência do furo e ela é recusada, com a mensagem dizendo o valor mínimo aceito. Somado ao advisory lock provado sob concorrência e à hash-chain resistindo a inversão e antedatação. |
| **Operações e novação** | 🟢 | As duas portas do mesmo furo fechadas: o valor da substituta e a janela em que ela nascia sem ocupar o teto. Renegociação legítima preservada — alongar prazo, capitalizar juros e reduzir na medida do que foi amortizado com lastro continuam passando. |
| **Cobrança** | 🟢 | Os três altos **fechados pela 027 e reproduzidos nos dois sentidos**: a chave do extrato virou `(documento, conta_origem)` com `NULLS NOT DISTINCT` (crédito do segundo banco entra; manual repetido segue recusado), o `INSERT` em `parcela` ganhou guarda (OC025) — com o `TRUNCATE` fechado junto, porque esvaziar a agenda reabria a janela em dois comandos —, e a cobertura de valor saiu de dentro de `fn_baixar_parcela` para o trigger (OC011), alcançável por qualquer porta. Sobre o que já era bom: lastro em duas camadas, parser OFX puro com mais de 30 testes, proveniência com CHECK. |
| **Contratos e registro** | 🟡 | Hash calculado pelo banco (provado por INSERT com hash forjado — o banco recalculou), corpo determinístico, gate OC004 real. O registro segue forjável em dois comandos por `enviado_em` antedatado, e confirmar registro não grava autor. |
| **Fiscal (Lucro Presumido)** | 🟡 | Núcleo sólido, as quatro correções da 018 são reais e testadas, a memória de cálculo confere. Todo excedente do crédito vira mora tributável — inclusive amortização de principal. E `parametro_fiscal` segue vazia, o que é recusa deliberada. |
| **Compliance PLD** | 🟡 | O domínio mais bem construído do levantamento: três invariantes em trigger, retenção ancorada no encerramento. Mas **produção não tem storage configurado** — arquivar responde 503, e o gate OC019 trava todo tomador novo. |
| **Segurança e auditoria** | 🔴 | Perímetro genuinamente fechado: as 50 rotas sob `/api` exigem autenticação, enumeradas com o app em modo produção. Derrubado pelo rate limit — um balde **único global** atrás do proxy do Railway, onde um anônimo nega serviço a todos os operadores. |
| **Rotinas e observabilidade** | 🔴 | Engenharia de operação de primeira linha, e testada de verdade. Mas o serviço de cron está **sete commits atrás**, o banner de vigilância mente há dias, e não há alerta ativo. |
| **Frontend** | 🟡 | Cobre quase todo o backend; `baseUrl` relativo nos dois modos com teste de regressão; dicionário de erro por código. A tela exibe o **piso** de retenção sob o rótulo "Guarda até" — exatamente o número que a migration 022 declarou não valer. |
| **Qualidade e CI** | 🟡 | 611 testes de backend e 216 de frontend passando, com peças excelentes: a guarda da suíte-fantasma, o teste de catálogo que pega ramo de escrita sem advisory lock. Mas o smoke do CI **deixou de provar** que as migrations aplicam — e continua afirmando que prova. Um `skipif` que conferia `shutil.which("bash") is not None` foi corrigido para **executar** a sonda: no Windows o `bash.exe` do WSL está no PATH mesmo sem distribuição instalada, e cinco testes ficavam vermelhos por motivo que não era defeito — o mesmo erro de guarda conferir presença onde o invariante é usabilidade. |
| **Infra e deploy** | 🔴 | Boa onde foi construída depois de um incidente, frágil onde nunca doeu. Backup sem cópia fora do provedor: dump e banco moram no mesmo projeto Railway. |

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
2. ~~**Três furos de cobrança.**~~ **Feito** (027): chave `(documento,
   conta_origem)` com `NULLS NOT DISTINCT`, guarda de `INSERT` em `parcela`
   (OC025) com o `TRUNCATE` fechado junto, e cobertura de valor no trigger
   (OC011).
3. ~~**`baixado_por`.**~~ **Feito** — uma linha no router, e um teste que passa
   pelo HTTP para provar que alguém a executa.
4. **Rate limit por cliente**, não um balde global. É o único alto de código que
   resta.
5. **Corrigir a documentação**, inclusive os docstrings que descrevem intenção
   como implementação.

**Dado a conferir antes de subir a 027**, e que ela deliberadamente não corrige
sozinha: baixas já gravadas contra movimento insuficiente. Só entram por SQL
direto (`fn_baixar_parcela` sempre recusou), a guarda nova é BEFORE ROW e não
revisita o que já está gravado, e reverter baixa é justamente o que este sistema
não faz. A consulta está no docstring do `upgrade()` da revisão 0027; havendo
linhas, a escolha entre reconciliar e encerrar por prejuízo é de negócio, não de
migration.

### Seu (configuração e decisão)

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

**Ainda não dá para entrar em produção com dinheiro real** — mas o motivo mudou
de natureza outra vez, e agora para melhor: **não há mais defeito de código no
que a lei exige**. O que impede é credencial e dado de negócio.

O sistema está impedido por duas razões distintas, e não confundi-las é o que
torna a fila acionável:

1. ~~**Defeito de código crítico**~~ — **fechado**. A novação (026) e os três
   altos de cobrança (027) foram reproduzidos nos dois sentidos. Resta um alto
   de segurança, o rate limit global, que degrada disponibilidade sob abuso e
   não fura invariante legal nenhum.
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
  os comentários que afirmam o contrário estão errados.
- **Os bytes do extrato não são arquivados** — só o hash.
- **O gate OC004 prova que alguém digitou um protocolo**, não que houve registro.
- **Backup e banco no mesmo provedor.**
- **Nenhum alerta ativo** — toda a observabilidade é pull e exige credencial.
