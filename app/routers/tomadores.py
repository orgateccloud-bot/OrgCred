"""
Router: cadastro e consulta de tomadores.

O gate geográfico (OC002) é enforced pelo trigger na ativação da operação;
`municipio_autorizado` aqui é dado cadastral — marcar como autorizado é
decisão operacional (admin), não validação automática. KYC (Receita,
listas restritivas) segue pendente — ver app/routers/compliance.py.
"""

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.models import Tomador, Usuario


router = APIRouter(prefix="/tomadores", tags=["tomadores"])


class TomadorOut(BaseModel):
    id: UUID
    cnpj: str
    razao_social: str
    porte: str
    municipio: str
    uf: str
    municipio_autorizado: bool
    created_at: datetime


class TomadorOperacaoResumoOut(BaseModel):
    id: UUID
    tipo: str
    valor_principal: str
    status: str
    created_at: datetime


class TomadorDetailOut(TomadorOut):
    operacoes: List[TomadorOperacaoResumoOut]


class CriarTomadorIn(BaseModel):
    cnpj: str = Field(pattern=r"^\d{14}$", description="Somente dígitos")
    razao_social: str = Field(min_length=1, max_length=255)
    porte: Literal["ME", "EPP"]
    municipio: str = Field(min_length=1, max_length=255)
    uf: str = Field(pattern=r"^[A-Z]{2}$")


class AtualizarAutorizacaoIn(BaseModel):
    municipio_autorizado: bool


@router.get("", response_model=List[TomadorOut])
def get_tomadores(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[TomadorOut]:
    rows = db.query(Tomador).order_by(Tomador.razao_social).all()
    return [TomadorOut.model_validate(t, from_attributes=True) for t in rows]


@router.get("/{tomador_id}", response_model=TomadorDetailOut)
def get_tomador(
    tomador_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> TomadorDetailOut:
    tomador: Optional[Tomador] = db.query(Tomador).filter(Tomador.id == tomador_id).one_or_none()
    if tomador is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")

    operacoes = db.execute(
        text("""
        select id, tipo, valor_principal, status, created_at
        from operacao_credito where tomador_id = :tomador_id
        order by created_at desc
    """),
        {"tomador_id": str(tomador_id)},
    ).all()

    base = TomadorOut.model_validate(tomador, from_attributes=True)
    return TomadorDetailOut(
        **base.model_dump(),
        operacoes=[
            TomadorOperacaoResumoOut(
                id=op.id,
                tipo=op.tipo,
                valor_principal=str(op.valor_principal),
                status=op.status,
                created_at=op.created_at,
            )
            for op in operacoes
        ],
    )


@router.post("", response_model=TomadorOut, status_code=201)
def post_criar_tomador(
    body: CriarTomadorIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> TomadorOut:
    """Cadastro nasce com municipio_autorizado=false — a autorização do gate
    geográfico é ato separado, restrito a admin (PATCH /autorizacao)."""
    tomador = Tomador(
        id=uuid4(),
        cnpj=body.cnpj,
        razao_social=body.razao_social,
        porte=body.porte,
        municipio=body.municipio,
        uf=body.uf,
        municipio_autorizado=False,
    )
    db.add(tomador)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"CNPJ {body.cnpj} já cadastrado.")
    db.refresh(tomador)
    return TomadorOut.model_validate(tomador, from_attributes=True)


@router.patch("/{tomador_id}/autorizacao", response_model=TomadorOut)
def patch_autorizacao(
    tomador_id: UUID,
    body: AtualizarAutorizacaoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> TomadorOut:
    """Liga/desliga a autorização do município (gate OC002). Admin only:
    é a chave que permite ativar crédito para o tomador."""
    tomador: Optional[Tomador] = db.query(Tomador).filter(Tomador.id == tomador_id).one_or_none()
    if tomador is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")
    tomador.municipio_autorizado = body.municipio_autorizado  # type: ignore[assignment]
    db.commit()
    db.refresh(tomador)
    return TomadorOut.model_validate(tomador, from_attributes=True)
