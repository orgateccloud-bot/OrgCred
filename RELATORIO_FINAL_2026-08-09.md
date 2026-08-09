# OrgCred — Relatório final da rodada de execução

**Período:** 2026-08-06 a 2026-08-09
**Escopo:** Frentes 2, 3 e 4 do plano de combate, mais os dois gates legais
**Base:** 9 commits em `main`, de `bdccab5` a `2031798`

---

## 1. Resumo executivo

O OrgCred entrou nesta rodada com **um núcleo de crédito sólido cercado por
quatro módulos regulatórios que eram stubs** — cobrança, contratos, fiscal e
compliance somavam 8 linhas de código e nenhum teste. Saiu com os quatro
construídos, cobertos e com os invariantes legais no banco.

O achado de maior gravidade não estava previsto no plano: **dois furos no
teto de capital do Art. 5º já em produção**, encontrados ao investigar o que
a renegociação fazia antes de escrever qualquer código de cobrança.

| Indicador | Antes | Depois |
|---|---:|---:|
| Testes backend | 63 | **209** |
| Cobertura backend | 88% | **92%** |
| Testes E2E | 3 | **5** |
| Migrations | 6 | **14** |
| Endpoints | 19 | **44** |
| SQLSTATEs (invariantes no banco) | 6 | **18** |
| Nota média do scorecard | 5,4 | **7,3** |
| Periferia regulatória | 0,6 | **7,0** |

**O sistema continua não operável** — e isso não mudou porque não depende de
código. Ver seção 6.

---

## 2. O achado grave: dois furos no Art. 5º em produção

Antes de escrever cobrança, investiguei o que a renegociação já fazia. O
resultado, medido contra Postgres real **antes de qualquer correção
existir**:

```
ativa -> liquidada     liberou R$ 40.000,00 | eventos no ledger: 1
ativa -> inadimplente  liberou R$ 40.000,00 | eventos no ledger: 0  <<<
ativa -> renegociada   liberou R$ 40.000,00 | eventos no ledger: 0  <<<
```

**Causa:** o capital comprometido era `sum(valor_principal) where status =
'ativa'`. Sair de `ativa` por qualquer porta tirava a operação da conta, mas
o trigger só gravava evento no ledger para `liquidada`/`cancelada`.

**Gravidade 1 — teto furado.** Marcar inadimplência liberava o capital de um
empréstimo NÃO pago. O dinheiro está lá fora e o sistema passava a permitir
emprestá-lo de novo. Violação do Art. 5º por construção, sem ninguém agir de
má-fé.

**Gravidade 2 — auditoria mentindo.** Movimento de capital sem evento
correspondente fazia a série temporal do dashboard mentir — e a cadeia
seguia "íntegra", porque nada foi adulterado, apenas omitido.

**Correção** (`bdccab5`): comprometido passou a ser
`status in ('ativa','inadimplente')`, e a renegociação virou **novação
atômica** (OC008) — baixa da original e criação da substituta na mesma
transação, sob o mesmo advisory lock.

> **Esses dois furos ainda estão em produção**, porque o Railway não faz
> deploy de `main` desde julho.

---

## 3. O que foi construído

### 3.1 Cobrança — ciclo completo (Frente 3)

| Peça | Invariante |
|---|---|
| Agenda de parcelas PRICE/SAC gerada **pelo banco** na ativação | OC009 — imutável depois de emitida |
| Novação atômica para renegociação | OC008 |
| Aging derivado da agenda + régua automática | OC010 — trilha de autoria append-only |
| Baixa de recebimento amarrada a movimento bancário | OC011/OC012 |

O ciclo fecha em si mesmo: a agenda define o que se cobra, o aging vê o
atraso a partir dela, e **só a baixa com lastro bancário** tira a parcela do
atraso. Sem essa amarra, bastaria um `UPDATE` para a régua parar de ver o
atraso de uma dívida em aberto — uma carteira podre passaria por saudável.

Duas decisões de matemática que sem teste teriam fechado errado em silêncio:

- **Taxa zero** divide por zero na fórmula PRICE. Tem desvio explícito.
- **Resíduo de arredondamento** vai todo na última parcela, então
  `sum(amortização)` bate exatamente no principal e o saldo devedor final é
  `0,00`. Sem isso, a quitação nunca fecha.

### 3.2 Compliance — o que não dependia de terceiro (Frente 4)

- **Identificação com evidência arquivada**: guarda o SHA-256, não o
  arquivo, com endpoint de conferência bit a bit.
- **Retenção de 5 anos** garantida por trigger (OC013). `retencao_ate` é
  materializada no ato — se o prazo legal mudar, os documentos já
  arquivados mantêm a regra vigente à época.
- **Detecção interna de atipicidade** (OC014, append-only): fracionamento,
  liquidação antecipada e pagamento em excesso.
- **Canal COAF como adaptador desligado**: os campos existem, nada os
  preenche. Quando o parecer sair, liga-se o envio sem tocar na detecção.

### 3.3 Fiscal — apuração da receita da ESC

Lucro Presumido, trimestral. IRPJ com base presumida, adicional só sobre o
excedente do limite, CSLL, e PIS/COFINS cumulativos sobre a receita.

- **A base é só o juro.** Amortização devolve principal e não é resultado.
- **Nenhuma alíquota embutida.** Sem parâmetro configurado, apurar é
  recusado (OC015) — devolver um número plausível calculado com alíquota
  escolhida pelo sistema seria pior do que não devolver nada.
- Parâmetros **com vigência**, copiados para dentro da apuração: uma
  declaração passada não muda de valor quando o parâmetro é alterado.
- Retificação **por versão** (OC016).

### 3.4 Contratos — instrumento e registro

- **Contrato de Empréstimo ESC** (não CCB — a CCB é instrumento de
  instituição financeira), gerado da operação e da agenda, **determinístico**,
  com SHA-256 **calculado pelo banco**: corpo e hash não podem divergir.
- **Registro como entidade de primeira classe**: entidade, protocolo
  obrigatório, máquina de estados com confirmado/rejeitado terminais
  (OC018).

### 3.5 Os dois gates legais ligados

| Gate | Antes | Depois |
|---|---|---|
| Registro em entidade registradora (OC004) | `registro_entidade_ref` texto livre — `"x"` passava | Exige registro **confirmado**, com protocolo |
| Identificação do tomador (OC019) | Nenhuma exigência | Exige ao menos uma evidência arquivada |

Ambos com a mesma disciplina: **não retroativos** (rodam na transição —
revogar o que já foi emprestado não devolveria o dinheiro) e **não
revalidam** na reativação de inadimplente.

Ligar o primeiro quebrou **98 testes**, e era o esperado. Nenhum gate foi
afrouxado para os testes passarem: os testes passaram a refletir a nova
realidade. Efeito colateral bom — os gates agora são exercidos dezenas de
vezes por execução da suíte.

---

## 4. Erros encontrados e corrigidos durante a execução

### 4.1 Três erros de Postgres que só produção teria mostrado

Todos pegos por teste **antes de existirem em produção**:

1. **`NULL` não conflita com `NULL` em chave única.** A regra de
   fracionamento grava `operacao_id` nulo, então a constraint ingênua
   deixava a varredura de atipicidade duplicar a ocorrência a cada execução.
   Um painel ruidoso é um painel que ninguém olha — o pior resultado
   possível para um controle de PLD.
2. **`now()` é o timestamp da transação, não do statement.** Numa trilha
   cujo propósito é mostrar sequência, isso empatava as linhas de uma
   novação e a ordem exibida virava arbitrária. Trocado por
   `clock_timestamp()`.
3. **`GET DIAGNOSTICS` só atribui, não avalia expressão.**

### 4.2 Bugs de UI que só o E2E pegou

- Query de parcelas não invalidada: a agenda só aparecia após reload manual.
- Diálogo da régua não fechava no sucesso — o Radix deixava a página inerte
  e a tela parecia travada.
- Badge de status ambíguo depois que a trilha passou a renderizar um por
  transição. A correção (`aria-label="Status atual: …"`) também conserta a
  acessibilidade.
- Seed do E2E não limpava `movimento_bancario`, tornando a suíte não
  repetível.

### 4.3 Regra de negócio saindo como falha de infraestrutura

Violação do índice único de registro confirmado vazava como **500**. Virou
409 com mensagem própria.

---

## 5. Decisões tomadas e por quê

| Decisão | Alternativa recusada | Motivo |
|---|---|---|
| Inadimplente **continua** comprometendo capital | Liberar o capital | O dinheiro não voltou |
| Renegociação = novação atômica | Transição simples | Dupla contagem fura o Art. 5º |
| Baixa é **terminal** (sem estorno) | Permitir reverter | Estorno exigiria trilha própria; melhor não ter o caminho do que ter um que apaga o lastro em silêncio |
| Régua **nunca** reativa sozinha | Reativar ao ver parcela paga | Confirmar que o dinheiro entrou é decisão de uma pessoa |
| Movimento precisa **cobrir** a parcela (≥) | Exigir valor igual | Juros de mora fazem pagar mais; exigir igualdade travaria todo pagamento atrasado |
| **Lucro Presumido**, alíquotas em configuração | Embutir alíquotas | Matéria tributária é do contador |
| **"Contrato de Empréstimo ESC"**, não CCB | Emitir CCB | CCB é instrumento de instituição financeira |
| `ORGCRED_ESC_*` **sem default** | Default plausível | Entraria num documento com efeito jurídico como se fosse dado real |
| OC019 com **código próprio** | Reusar OC004 | Leis diferentes, instruções diferentes ao operador |
| Identificação checada **antes** do gate geográfico | Ordem arbitrária | Não saber quem é o tomador é falha mais grave |

Em nenhum momento inventei valor de capital social, alíquota ou dado da ESC.
Onde a informação é do negócio, o sistema **recusa** em vez de assumir.

---

## 6. O que falta — e nada disso é código

| # | Ação | Quem | Esforço |
|---|---|---|---|
| 1 | **Reconectar o GitHub no Railway** (`main`, builder Dockerfile) | você | 30 min |
| 2 | Valor do capital social integralizado | **sócios** | 5 min após decidir |
| 3 | Senha do admin no Supabase + linha em `usuario` | você | 15 min |
| 4 | Autorizar o CircleCI no GitHub | você | 20 min |
| 5 | Preencher `ORGCRED_ESC_*` com os dados reais | você | 5 min |
| 6 | Contador preenche presunção e alíquotas | contador | 15 min |
| 7 | Escolher entidade registradora (CRDC, Núclea, SPC Grafeno, B3, CERC) | você | contato comercial |
| 8 | Parecer sobre IOF em ESC | contador/advogado | — |
| 9 | Confirmação do regime PLD/COAF | advogado | — |

**Item 1 é o mais urgente**, e não por conveniência: produção roda hoje a
versão **com os dois furos do Art. 5º** descritos na seção 2, sem os gates e
sem nenhum dos quatro módulos construídos.

**Item 2 é o de maior alavancagem.** Sem ele o teto é R$ 0,00 e nenhuma
operação ativa — o sistema inteiro é uma vitrine.

### Antes do deploy

Com os gates ligados, medir o que ficará travado:

```sql
select * from v_operacoes_sem_registro_confirmado;
select * from v_tomadores_sem_identificacao;
```

Operações já ativas não são afetadas.

---

## 7. Commits desta rodada

| Commit | Entrega |
|---|---|
| `bdccab5` | Fecha os dois furos do teto do Art. 5º (inadimplência e novação) |
| `4d5edc4` | Agenda de parcelas gerada pelo banco, imutável |
| `34b5b20` | Aging de inadimplência, régua automática e trilha de autoria |
| `39d29a1` | Baixa de recebimento amarrada a movimentação bancária |
| `ba3997b` | Compliance: identificação, retenção de 5 anos e atipicidade |
| `ff02c19` | Fiscal: apuração no Lucro Presumido |
| `3394487` | Contratos: instrumento com hash do banco e registro com protocolo |
| `8e5e6cc` | Liga o gate do Art. 5º §3º (registro confirmado) |
| `2031798` | Liga o gate de identificação do tomador (OC019) |

Todos com suíte verde, ruff/ruff format/mypy/bandit limpos, e validados
contra Postgres 16 real.
