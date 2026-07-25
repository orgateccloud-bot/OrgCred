"""Router: consulta de capital disponível e gestão do capital social."""

from datetime import datetime
from decimal import Decimal
from typing import List, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.capital_engine import (
    consultar_capital_disponivel,
    consultar_capital_snapshot,
    registrar_evento_capital,
)
from app.core.security import get_admin_user, get_current_user
from app.db import get_db
from app.models import EscCapitalSocial, Usuario


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


class CapitalEventoOut(BaseModel):
    id: UUID
    valor: Decimal
    tipo_evento: str
    created_at: datetime


class CriarCapitalEventoIn(BaseModel):
    valor: Decimal = Field(gt=0)
    tipo_evento: Literal["constituicao", "reducao"]


@router.get("/eventos", response_model=List[CapitalEventoOut])
def get_capital_eventos(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[CapitalEventoOut]:
    """Histórico de eventos de capital social (constituições/aportes e
    reduções) — a soma é o teto exibido em /capital/snapshot."""
    rows = db.query(EscCapitalSocial).order_by(EscCapitalSocial.created_at.desc()).all()
    return [CapitalEventoOut.model_validate(e, from_attributes=True) for e in rows]


@router.post("/eventos", response_model=CapitalEventoOut, status_code=201)
def post_capital_evento(
    body: CriarCapitalEventoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> CapitalEventoOut:
    """
    Registra aporte ('constituicao' — a view soma ambos igualmente) ou
    redução de capital. Admin only: altera o teto legal da ESC (Art. 5º,
    LC 167/2019). A proteção OC005 (redução abaixo do comprometido) é o
    trigger; erros propagam no contrato global {detail, codigo}.
    """
    evento = registrar_evento_capital(db, valor=body.valor, tipo_evento=body.tipo_evento)
    return CapitalEventoOut.model_validate(evento, from_attributes=True)
