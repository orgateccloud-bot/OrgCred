"""
Router: régua de cobrança — inadimplência, regularização e renegociação.

STATUS: transições de estado e novação atômica implementadas (migration
006 define a regra de capital; app/capital_engine.py executa). A regra
explícita de renegociação exigida pela REVISAO_2026-07-11 (item 3) é:
novação em UMA transação sob o advisory lock do teto — a antiga sai do
conjunto comprometido (evento 'renegociacao_liberacao' no ledger) e a
nova entra pelo gate completo; nenhum estado commitado conta em dobro.

Pendências que continuam abertas (integrações externas, não bloqueiam):
- Detecção automática de atraso: ainda não existe tabela de parcelas —
  a marcação de inadimplência é decisão manual do operador por enquanto.
- Notificação automática ao tomador (email/SMS) por faixa de atraso.
- Negativação em bureaus de crédito (Serasa/SPC) após prazo configurável.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.capital_engine import (
    TermosRenegociacao,
    marcar_inadimplente,
    regularizar_operacao,
    renegociar_operacao,
)
from app.core.security import get_operador_user
from app.db import get_db
from app.models import SistemaAmortizacao, Usuario


router = APIRouter(prefix="/cobranca", tags=["cobranca"])


class OperacaoResumo(BaseModel):
    id: UUID
    status: str
    valor_principal: Decimal
    registro_entidade_ref: Optional[str]

    class Config:
        from_attributes = True


class RenegociacaoIn(BaseModel):
    """Termos negociados da nova operação criada pela novação."""

    valor_principal: Decimal = Field(..., gt=0, description="Principal negociado da nova operação")
    taxa_juros_mensal: Decimal = Field(..., ge=0)
    numero_parcelas: int = Field(..., ge=1)
    sistema_amortizacao: SistemaAmortizacao
    registro_entidade_ref: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Registro da NOVA operação na entidade registradora — novação é "
            "contrato novo, o Art. 5º §3º exige registro próprio (OC004)."
        ),
    )


class RenegociacaoOut(BaseModel):
    antiga: OperacaoResumo
    nova: OperacaoResumo


@router.post("/operacoes/{operacao_id}/inadimplencia", response_model=OperacaoResumo)
def post_marcar_inadimplente(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoResumo:
    """
    Marca operação em atraso: 'ativa' -> 'inadimplente'.

    NÃO libera capital (migration 006): a operação em atraso continua
    comprometendo o teto até liquidação ou renegociação.

    Requires: operador ou admin. Erros: 404 inexistente; 409 OC003.
    """
    op = marcar_inadimplente(db, operacao_id, usuario_id=str(user.id))
    return OperacaoResumo.model_validate(op)


@router.post("/operacoes/{operacao_id}/regularizacao", response_model=OperacaoResumo)
def post_regularizar_operacao(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoResumo:
    """
    Cura do atraso: 'inadimplente' -> 'ativa'. Movimento interno ao
    conjunto comprometido — nenhum capital novo, nenhum gate re-executa.

    Requires: operador ou admin. Erros: 404 inexistente; 409 OC003.
    """
    op = regularizar_operacao(db, operacao_id, usuario_id=str(user.id))
    return OperacaoResumo.model_validate(op)


@router.post("/operacoes/{operacao_id}/renegociacao", response_model=RenegociacaoOut)
def post_renegociar_operacao(
    operacao_id: UUID,
    payload: RenegociacaoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> RenegociacaoOut:
    """
    Novação atômica: antiga ('ativa'|'inadimplente') -> 'renegociada' e
    nova operação ativada com os termos negociados, tudo em uma transação
    sob o lock do teto. Se a nova não couber no capital (OC001), NADA
    muda — a antiga permanece como estava.

    Requires: operador ou admin.
    Erros: 404 inexistente; 409 OC003 (estado não renegociável);
    422 OC001/OC002/OC004 (gate da nova operação).
    """
    antiga, nova = renegociar_operacao(
        db,
        operacao_id,
        TermosRenegociacao(
            valor_principal=payload.valor_principal,
            taxa_juros_mensal=payload.taxa_juros_mensal,
            numero_parcelas=payload.numero_parcelas,
            sistema_amortizacao=payload.sistema_amortizacao.value,
            registro_entidade_ref=payload.registro_entidade_ref,
        ),
        usuario_id=str(user.id),
    )
    return RenegociacaoOut(
        antiga=OperacaoResumo.model_validate(antiga),
        nova=OperacaoResumo.model_validate(nova),
    )
