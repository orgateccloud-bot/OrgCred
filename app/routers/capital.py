"""Router: consulta de capital disponível."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.capital_engine import consultar_capital_disponivel, consultar_capital_snapshot
from app.core.security import get_current_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/capital", tags=["capital"])


class CapitalDisponivelOut(BaseModel):
    disponivel: Decimal


class CapitalSnapshotOut(BaseModel):
    total: Decimal
    comprometido: Decimal
    disponivel: Decimal


@router.get("/disponivel", response_model=CapitalDisponivelOut)
def get_capital_disponivel(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> CapitalDisponivelOut:
    """
    Leitura informativa para UX — a validação real do teto acontece no
    trigger em ativação. Entre esta leitura e um POST /operacoes/{id}/ativar,
    outra transação pode consumir o capital exibido; o cliente deve tratar
    o código OC001 como resultado normal, não como erro inesperado.
    """
    disponivel = consultar_capital_disponivel(db)
    return CapitalDisponivelOut(disponivel=disponivel)


@router.get("/snapshot", response_model=CapitalSnapshotOut)
def get_capital_snapshot(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> CapitalSnapshotOut:
    """Total/comprometido/disponível para a barra de utilização do teto no
    dashboard. Mesma ressalva de leitura informativa que /disponivel."""
    snapshot = consultar_capital_snapshot(db)
    return CapitalSnapshotOut(
        total=snapshot.total, comprometido=snapshot.comprometido, disponivel=snapshot.disponivel
    )
