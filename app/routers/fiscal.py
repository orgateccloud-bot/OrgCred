"""
Router: apuração fiscal das operações (IOF, tributação da receita).

STATUS: stub — parcialmente bloqueado por decisão de negócio pendente.

BLOQUEADOR: regime de IOF não confirmado. Não está determinado se IOF-crédito
incide sobre operações de ESC, e se incidir, quem arca com o custo (a ESC ou
o tomador) — depende de parecer jurídico-tributário, não de escolha técnica.
Ver DECISOES_PENDENTES.md.

O QUE NÃO está bloqueado (mas não está implementado):
- Regime de tributação da receita da própria ESC (Lucro Presumido/Real —
  ESC não pode optar pelo Simples Nacional por vedação legal) já está
  determinado na literatura, só falta implementar o cálculo.

Escopo pendente após a decisão do IOF:
- Cálculo de IOF por operação (se aplicável) e armazenamento em
  operacao_credito (colunas iof_valor, iof_pago — ainda não existem no
  schema; adicionar em nova migration quando a decisão sair).
- Gate de ativação: se IOF for devido e não pago, bloquear ativação
  (SQLSTATE novo, ex. OC006).
- Apuração periódica da receita de juros para fins de IRPJ/CSLL.
"""

from fastapi import APIRouter


router = APIRouter(prefix="/fiscal", tags=["fiscal"])
