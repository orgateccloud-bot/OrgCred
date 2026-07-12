# OrgCred — Decisões de negócio pendentes (Fase 6)

**Data:** 2026-07-12 · Bloqueadores identificados na revisão de arquitetura
(ver `RELATORIO_MODERNIZACAO_2026-07-12.md`) que **não podem ser resolvidos
por implementação técnica** — exigem decisão do dono do negócio, parecer
jurídico-tributário ou negociação comercial. Este documento existe para que
a próxima sessão de trabalho comece direto na decisão, não na investigação.

---

## 1. Entidade registradora (bloqueia `app/routers/contratos.py`)

**O que é:** o Art. 5º §3º da LC 167/2019 exige que operações de crédito de
uma ESC sejam registradas em entidade apodada pelo Banco Central antes da
ativação. O sistema já **enforcement** isso — `operacao_credito.registro_entidade_ref`
é obrigatório para ativar (SQLSTATE OC004) — mas hoje esse campo é
preenchido manualmente, sem integração real.

**Candidatas identificadas (não confirmadas, levantamento não-exaustivo):**
- CERC
- Núclea (ex-CIP)
- TAG

**Decisão necessária:** qual entidade, condições comerciais (custo por
registro, SLA de integração), e se a API dela é REST/webhook (compatível
com o padrão já usado no resto do sistema) ou exige outro protocolo.

**Depois da decisão:** implementar `app/routers/contratos.py` — geração de
CCB, chamada à API da entidade, callback de confirmação que preenche
`registro_entidade_ref`.

---

## 2. Regime de IOF (bloqueia metade de `app/routers/fiscal.py`)

**O que é:** não está determinado se IOF-crédito incide sobre operações de
uma ESC e, se incidir, quem arca com o custo (a ESC ou o tomador).

**Decisão necessária:** parecer jurídico-tributário confirmando (a) se há
incidência, (b) a alíquota aplicável, (c) o responsável pelo recolhimento.

**Depois da decisão:** migration nova adicionando `iof_valor`/`iof_pago` em
`operacao_credito`; gate de ativação (SQLSTATE novo, ex. OC006) se IOF for
devido e não pago.

---

## 3. Capital social inicial (bloqueia o teto operacional real)

**O que é:** sem o valor do capital social integralizado, o teto legal do
Art. 5º (total de operações ativas ≤ capital social) é desconhecido — o
sistema está tecnicamente pronto (trigger + advisory lock testados), mas
não há `esc_capital_social` com evento `constituicao` em produção.

**Decisão necessária:** valor definido pelos sócios, confirmado como
efetivamente integralizado (não apenas subscrito).

**Depois da decisão:** `insert into esc_capital_social (valor, tipo_evento)
values (<valor>, 'constituicao')` — uma linha, sem mudança de código.

---

## 4. Divisão societária entre os sócios

Registrada como pendência no `REVISAO_2026-07-11.md`, sem insistência — os
sócios decidiram tratar depois. Não bloqueia nenhum caminho técnico
atual; relevante só se/quando o sistema precisar refletir participação
societária (ex. relatórios de distribuição de lucro).

---

## 5. Status regulatório de PLD/COAF para ESC

**O que é:** não confirmado se a ESC está sujeita a comunicação COAF como
as demais instituições financeiras, nem sob qual regime específico.

**Decisão necessária:** confirmação jurídica de que órgão supervisiona ESC
para fins de PLD/FT e quais comunicações são obrigatórias.

**Depois da decisão:** implementar `app/routers/compliance.py` — hoje é
stub. Nota: a propagação de `usuario_id` para a trilha de auditoria (quem
executou cada ativação) **já foi implementada** (migration 004,
independente desta decisão) — o que falta é especificamente a integração
com comunicações regulatórias externas.

---

## O que NÃO está bloqueado (só não implementado ainda)

Para não confundir bloqueio de decisão com trabalho técnico pendente:

- **Renegociação sem dupla contagem** (`app/routers/cobranca.py`): precisa
  de uma regra explícita de novação atômica, mas é decisão de design técnico,
  não de negócio externo — pode ser feita a qualquer momento.
- **Amortização parcial libera capital**: interpretação conservadora atual
  (usa `valor_principal` integral até liquidação) é juridicamente segura;
  mudar para saldo devedor é decisão de interpretação contábil-jurídica
  interna, não depende de terceiros.
- **Onboarding/KYC de tomadores** (`app/routers/tomadores.py`): escopo
  técnico normal, sem bloqueador externo identificado.
