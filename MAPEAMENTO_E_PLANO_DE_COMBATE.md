# OrgCred — Mapeamento, scorecard e plano de entrada em produção

> **Levantamento independente de 2026-08-18.** 41 agentes sobre 11 domínios,
> com rodada adversarial: todo achado grave passou por um cético encarregado de
> **refutá-lo**. **22 sobreviveram** — 2 críticos, 9 altos, 10 médios, 1 baixo.
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

**Não é explorável em produção hoje**, porque o capital social é R$ 0,00 e não há
operação nenhuma. Precisa estar fechado **antes** de o capital ser carregado —
que é o último passo da fila de configuração.

---

## 1. Retrato em uma frase

O sistema tem invariantes legais genuinamente bem construídos no banco e uma
rede de testes acima da média — e, ao mesmo tempo, **um furo crítico aberto no
invariante central**, três altos em cobrança, e uma documentação que afirmava
estar tudo fechado.

---

## 2. Scorecard por domínio

Verde exige implementado **e** testado **e** sem achado confirmado em aberto.

| Domínio | Nota | Por quê |
|---|---|---|
| **Capital e teto (Art. 5º)** | 🔴 | Saída livre pela novação, reproduzida. O resto é sólido: advisory lock provado sob concorrência, hash-chain em `seq` resistindo a inversão e a antedatação. |
| **Operações e novação** | 🔴 | O mesmo furo pelo lado do ciclo de vida, mais uma falha alta independente: a substituta nasce em `registrada` — que não ocupa o teto — enquanto a original já saiu do comprometido **no mesmo comando**, sem prazo para ativá-la. |
| **Cobrança** | 🔴 | Muito bem construído no banco: lastro em duas camadas, parser OFX puro com mais de 30 testes, proveniência com CHECK. Três altos, porém: `INSERT` em `parcela` sem guarda, `UPDATE` direto baixando sem cobertura de valor, e FITID colidindo entre contas descartando crédito real **com o relatório dizendo que nada faltou**. |
| **Contratos e registro** | 🟡 | Hash calculado pelo banco (provado por INSERT com hash forjado — o banco recalculou), corpo determinístico, gate OC004 real. O registro segue forjável em dois comandos por `enviado_em` antedatado, e confirmar registro não grava autor. |
| **Fiscal (Lucro Presumido)** | 🟡 | Núcleo sólido, as quatro correções da 018 são reais e testadas, a memória de cálculo confere. Todo excedente do crédito vira mora tributável — inclusive amortização de principal. E `parametro_fiscal` segue vazia, o que é recusa deliberada. |
| **Compliance PLD** | 🟡 | O domínio mais bem construído do levantamento: três invariantes em trigger, retenção ancorada no encerramento. Mas **produção não tem storage configurado** — arquivar responde 503, e o gate OC019 trava todo tomador novo. |
| **Segurança e auditoria** | 🔴 | Perímetro genuinamente fechado: as 50 rotas sob `/api` exigem autenticação, enumeradas com o app em modo produção. Derrubado pelo rate limit — um balde **único global** atrás do proxy do Railway, onde um anônimo nega serviço a todos os operadores. |
| **Rotinas e observabilidade** | 🔴 | Engenharia de operação de primeira linha, e testada de verdade. Mas o serviço de cron está **sete commits atrás**, o banner de vigilância mente há dias, e não há alerta ativo. |
| **Frontend** | 🟡 | Cobre quase todo o backend; `baseUrl` relativo nos dois modos com teste de regressão; dicionário de erro por código. A tela exibe o **piso** de retenção sob o rótulo "Guarda até" — exatamente o número que a migration 022 declarou não valer. |
| **Qualidade e CI** | 🟡 | 570 testes passando, com peças excelentes: a guarda da suíte-fantasma, o teste de catálogo que pega ramo de escrita sem advisory lock. Mas o smoke do CI **deixou de provar** que as migrations aplicam — e continua afirmando que prova. |
| **Infra e deploy** | 🔴 | Boa onde foi construída depois de um incidente, frágil onde nunca doeu. Backup sem cópia fora do provedor: dump e banco moram no mesmo projeto Railway. |

---

## 3. Achados confirmados

### Críticos

| Achado | Onde |
|---|---|
| A renegociação libera o teto integral sem prova de pagamento | [operacoes.py:522](app/routers/operacoes.py:522) |
| Novação devolve capital ao teto sem prova — a porta dos fundos do OC022 | [006:254](migrations/006_novacao_e_inadimplencia.sql:254) |

### Altos

| Achado | Onde |
|---|---|
| Janela ilimitada entre a baixa da original e a ativação da substituta | [006:262](migrations/006_novacao_e_inadimplencia.sql:262) |
| A autoria da baixa nunca é gravada pelo único caminho de produção | [cobranca.py:476](app/routers/cobranca.py:476) |
| `INSERT` em `parcela` sem guarda nenhuma — a agenda emitida aceita apêndice | [007:75](migrations/007_agenda_de_parcelas.sql:75) |
| `UPDATE` direto baixa parcela sem cobertura de valor | [016:204](migrations/016_bordas_da_cobranca.sql:204) |
| FITID colidindo entre contas descarta crédito real e o relatório fecha mesmo assim | [009:39](migrations/009_baixa_de_recebimento.sql:39) |
| Produção sem storage: arquivar responde 503 e OC019 trava todo tomador novo | [config.py:91](app/core/config.py:91) |
| Rate limit é um balde único global atrás do proxy | [main.py:196](app/main.py:196) |
| O cron não reconstrói no push — a trilha 025 pode não existir em produção | [OPERACAO.md](docs/OPERACAO.md) |

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
- **"a baixa tem autor"** — `parcela.baixado_por` é NULL em **100%** das baixas
  feitas pela API. Verificado pelo endpoint HTTP, que devolveu 204 com a coluna
  vazia.
- **"o relatório permite conferir que nenhuma linha do extrato se perdeu"** —
  falha exatamente no caso em que mais importa: com FITID colidindo entre contas,
  a aritmética fecha **enquanto a linha se perde**.
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

1. **Gate de valor na novação.** Fecha o crítico. É o único item que precisa
   estar pronto **antes** de o capital social ser carregado.
2. **Três furos de cobrança:** chave FITID composta com a conta, guarda de
   `INSERT` em `parcela`, e cobertura de valor no trigger — não só dentro de
   `fn_baixar_parcela`.
3. **`baixado_por`** — uma linha: o endpoint não passa `usuario_id`.
4. **Rate limit por cliente**, não um balde global.
5. **Corrigir a documentação**, inclusive os docstrings que descrevem intenção
   como implementação.

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

**Não dá para entrar em produção com dinheiro real hoje** — e o motivo mudou de
natureza desde o documento anterior: não é falta de dado de negócio, é **um furo
de código no invariante central**.

O sistema está impedido por três razões distintas, e não confundi-las é o que
torna a fila acionável:

1. **Defeito de código crítico e aberto** — a novação. Mais três altos em
   cobrança e um em segurança.
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
