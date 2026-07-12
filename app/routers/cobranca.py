"""
Router: régua de cobrança de operações inadimplentes.

STATUS: stub — não bloqueado por decisão externa, mas não implementado.
Depende de app/routers/contratos.py e da definição do fluxo de renegociação
(ver REVISAO_2026-07-11.md, item 3: "Fluxo de renegociação indefinido" —
se renegociar cria uma nova operação, o capital pode ser contado em dobro;
precisa de regra explícita, tratada sob o mesmo pg_advisory_xact_lock do
teto de capital, antes de qualquer renegociação real).

Escopo pendente:
- Identificação de operações com parcela em atraso -> transição para status
  'inadimplente' (transição já permitida pela máquina de estados do trigger:
  ativa -> inadimplente).
- Notificação automática ao tomador (email/SMS) por faixa de atraso.
- Negativação em bureaus de crédito (Serasa/SPC) após prazo configurável.
- Renegociação: novação atômica (liquida a operação antiga com evento
  próprio no ledger + ativa a nova, sob o mesmo lock) — ver nota acima.
"""

from fastapi import APIRouter


router = APIRouter(prefix="/cobranca", tags=["cobranca"])
