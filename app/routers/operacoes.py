"""Router: ciclo de vida de operações de crédito."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, liquidar_operacao
from app.core.security import get_operador_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/operacoes", tags=["operacoes"])


class OperacaoOut(BaseModel):
    id: UUID
    status: str
    valor_principal: Decimal

    class Config:
        from_attributes = True


@router.post("/{operacao_id}/ativar", response_model=OperacaoOut)
def post_ativar_operacao(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoOut:
    """
    Ativar operação de crédito (transição para status 'ativa').

    Erros de negócio saem pelos exception handlers centrais (app/main.py),
    com payload {"detail": <mensagem>, "codigo": <SQLSTATE>}.

    Requires: operador ou admin
    Responses:
      - 200: Operação ativada com sucesso
      - 401: Token ausente ou inválido
      - 403: Usuário sem permissão (não é operador)
      - 404: Operação não existe
      - 409: Transição de estado inválida (OC003)
      - 422: Regra de negócio violada (OC001 teto, OC002 município,
             OC004 registro na entidade)
    """
    op = ativar_operacao(db, operacao_id, usuario_id=str(user.id))
    return OperacaoOut.model_validate(op)


@router.post("/{operacao_id}/liquidar", response_model=OperacaoOut)
def post_liquidar_operacao(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoOut:
    """
    Liquidar operação ('ativa'|'inadimplente' -> 'liquidada').

    Libera o capital comprometido — o trigger grava o evento 'liquidacao'
    no ledger sob o mesmo lock do teto.

    Requires: operador ou admin
    Responses:
      - 200: Operação liquidada
      - 401/403: autenticação/autorização
      - 404: Operação não existe
      - 409: Transição de estado inválida (OC003)
    """
    op = liquidar_operacao(db, operacao_id, usuario_id=str(user.id))
    return OperacaoOut.model_validate(op)
