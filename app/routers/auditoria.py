"""Router: trilha de auditoria do capital_ledger (hash-chain, migration 005)."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/auditoria", tags=["auditoria"])


class LedgerEventoOut(BaseModel):
    id: UUID
    evento_tipo: str
    valor: Decimal
    operacao_id: Optional[UUID]
    saldo_disponivel_pos: Decimal
    usuario_nome: Optional[str]
    created_at: datetime
    prev_hash: Optional[str]
    current_hash: Optional[str]


class QuebraCadeia(BaseModel):
    id: UUID
    motivo: str


class AuditoriaOut(BaseModel):
    integro: bool
    quebras: List[QuebraCadeia]
    eventos: List[LedgerEventoOut]


@router.get("", response_model=AuditoriaOut)
def get_auditoria(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AuditoriaOut:
    """
    Trilha de auditoria em duas camadas: eventos legíveis (com nome do
    usuário quando disponível) e o resultado da verificação da cadeia de
    hash (`fn_verificar_cadeia_ledger()`, migration 005) — 0 quebras
    significa cadeia íntegra.
    """
    quebras_rows = db.execute(text("select id, motivo from fn_verificar_cadeia_ledger()")).all()
    quebras = [QuebraCadeia(id=row.id, motivo=row.motivo) for row in quebras_rows]

    eventos_rows = db.execute(
        text("""
        select
            l.id, l.evento_tipo, l.valor, l.operacao_id, l.saldo_disponivel_pos,
            u.nome as usuario_nome, l.created_at, l.prev_hash, l.current_hash
        from capital_ledger l
        left join usuario u on u.id::text = l.usuario_id
        -- seq (migration 006) desempata eventos da mesma transação (ex.
        -- novação) na MESMA ordem da cadeia de hash — id (uuid) é aleatório.
        order by l.created_at desc, l.seq desc
    """)
    ).all()
    eventos = [
        LedgerEventoOut(
            id=row.id,
            evento_tipo=row.evento_tipo,
            valor=row.valor,
            operacao_id=row.operacao_id,
            saldo_disponivel_pos=row.saldo_disponivel_pos,
            usuario_nome=row.usuario_nome,
            created_at=row.created_at,
            prev_hash=row.prev_hash,
            current_hash=row.current_hash,
        )
        for row in eventos_rows
    ]

    return AuditoriaOut(integro=len(quebras) == 0, quebras=quebras, eventos=eventos)
