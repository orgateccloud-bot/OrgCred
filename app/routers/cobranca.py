"""
Router: cobrança — renegociação por novação atômica.

A regra explícita de renegociação exigida pela REVISAO_2026-07-11 (item 3):
novação em UMA transação sob o advisory lock do teto — a antiga sai do
conjunto comprometido (evento 'renegociacao_liberacao' no ledger, migration
006) e a nova entra pelo gate completo; nenhum estado commitado conta
capital em dobro, e nenhum capital é liberado sem a nova operação ativa.

As demais transições da régua vivem em /operacoes (marcar-inadimplente,
ativar para regularização, liquidar) — este router existe para o passo que
NÃO pode ser composto por transições soltas sem perder atomicidade. O
POST /operacoes/{id}/renegociar (usado pelo painel) apenas libera a
antiga; o painel formaliza a nova operação em passos manuais — este
endpoint é a alternativa que faz a troca inteira de uma vez.

Pendências que continuam abertas (integrações externas, não bloqueiam):
- Detecção automática de atraso (não existe tabela de parcelas ainda).
- Notificação automática ao tomador (email/SMS) por faixa de atraso.
- Negativação em bureaus de crédito (Serasa/SPC) após prazo configurável.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.capital_engine import TermosRenegociacao, renegociar_operacao
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
