"""Router: ciclo de vida de operações de crédito."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.capital_engine import (
    MunicipioNaoAutorizado,
    OperacaoNaoEncontrada,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    TetoCapitalExcedido,
    TransicaoInvalida,
    ativar_operacao,
)
from app.db import get_db


router = APIRouter(prefix="/operacoes", tags=["operacoes"])


class AtivarOperacaoOut(BaseModel):
    id: UUID
    status: str
    valor_principal: Decimal


@router.post("/{operacao_id}/ativar", response_model=AtivarOperacaoOut)
def post_ativar_operacao(operacao_id: UUID, db: Session = Depends(get_db)) -> AtivarOperacaoOut:
    """422 = regra de negócio do banco recusou; 404 = não existe;
    409 = estado não permite a transição."""
    try:
        op = ativar_operacao(db, operacao_id)
    except OperacaoNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TransicaoInvalida as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (
        TetoCapitalExcedido,
        MunicipioNaoAutorizado,
        RegistroEntidadeAusente,
        ReducaoCapitalBloqueada,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return AtivarOperacaoOut(
        id=op.id,  # type: ignore[arg-type]
        status=op.status,  # type: ignore[arg-type]
        valor_principal=op.valor_principal,  # type: ignore[arg-type]
    )
