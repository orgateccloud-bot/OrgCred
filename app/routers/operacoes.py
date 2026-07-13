"""Router: ciclo de vida de operações de crédito."""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.exceptions import OperacaoNaoEncontrada, RegraNegocioViolada
from app.core.security import get_operador_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/operacoes", tags=["operacoes"])


class AtivarOperacaoOut(BaseModel):
    id: UUID
    status: str
    valor_principal: Decimal


class ErrorResponse(BaseModel):
    """Resposta de erro estruturada com código SQLSTATE."""

    codigo: Optional[str] = None
    detalhe: str


@router.post("/{operacao_id}/ativar", response_model=AtivarOperacaoOut)
def post_ativar_operacao(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> AtivarOperacaoOut:
    """
    Ativar operação de crédito (transição para status 'ativa').

    Requires: operador ou admin
    Responses:
      - 200: Operação ativada com sucesso
      - 401: Token ausente ou inválido
      - 403: Usuário sem permissão (não é operador)
      - 404: Operação não existe
      - 409: Transição de estado inválida
      - 422: Regra de negócio violada (teto, município, registro, capital)
    """
    try:
        op = ativar_operacao(db, operacao_id, usuario_id=str(user.id))
    except OperacaoNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RegraNegocioViolada as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail=ErrorResponse(codigo=exc.sqlstate, detalhe=exc.message).model_dump(),
        )

    return AtivarOperacaoOut(
        id=op.id,  # type: ignore[arg-type]
        status=op.status,  # type: ignore[arg-type]
        valor_principal=op.valor_principal,  # type: ignore[arg-type]
    )
