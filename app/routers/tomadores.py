"""
Router: onboarding e cadastro de tomadores.

STATUS: cadastro implementado. KYC externo (Receita Federal, listas
restritivas COAF/OFAC) permanece pendente — ver DECISOES_PENDENTES.md e
app/routers/compliance.py; aquele acoplamento com terceiros é o que ainda
não está resolvido, não o CRUD de tomador.

Implementado aqui:
- POST /tomadores           cadastra tomador (operador+), validando CNPJ
                            (dígito verificador), porte (MEI/ME/EPP, LC
                            167/2019) e unicidade do CNPJ.
- GET  /tomadores           lista tomadores.
- GET  /tomadores/{id}      lê um tomador.
- PATCH /tomadores/{id}/municipio-autorizado
                            gate geográfico (admin) — antes era feito
                            manualmente via SQL, agora é uma decisão
                            explícita e auditável de administrador.

O tomador nasce SEMPRE com municipio_autorizado=false: liberar a área de
atuação é uma decisão de administrador, não um efeito colateral do cadastro.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.cnpj import cnpj_valido, normalizar_cnpj
from app.core.exceptions import (
    CnpjInvalido,
    PorteInvalido,
    TomadorDuplicado,
    TomadorNaoEncontrado,
)
from app.core.security import get_admin_user, get_operador_user
from app.db import get_db
from app.models import PorteTomador, Tomador, Usuario


router = APIRouter(prefix="/tomadores", tags=["tomadores"])


class TomadorIn(BaseModel):
    cnpj: str = Field(..., description="CNPJ, com ou sem máscara (14 dígitos)")
    razao_social: str = Field(..., min_length=1, max_length=255)
    porte: str = Field(..., description="MEI, ME ou EPP (LC 167/2019)")
    municipio: str = Field(..., min_length=1, max_length=255)
    uf: str = Field(..., min_length=2, max_length=2)


class TomadorOut(BaseModel):
    id: UUID
    cnpj: str
    razao_social: str
    porte: str
    municipio: str
    uf: str
    municipio_autorizado: bool

    class Config:
        from_attributes = True


class MunicipioAutorizadoIn(BaseModel):
    autorizado: bool = Field(..., description="Libera (true) ou revoga (false) a área de atuação")


@router.post("", response_model=TomadorOut, status_code=201)
def cadastrar_tomador(
    payload: TomadorIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> TomadorOut:
    """
    Cadastra um tomador. Requires: operador ou admin.

    Validações de negócio:
      - CNPJ bem-formado e com dígito verificador válido (TM001).
      - Porte dentro do enquadramento da ESC — MEI/ME/EPP (TM002).
      - CNPJ ainda não cadastrado (TM003).

    O tomador é criado com municipio_autorizado=false; a liberação da área
    de atuação é feita separadamente via PATCH (admin).
    """
    cnpj = normalizar_cnpj(payload.cnpj)
    if not cnpj_valido(cnpj):
        raise CnpjInvalido(f"CNPJ inválido: '{payload.cnpj}'")

    porte = payload.porte.strip().upper()
    portes_validos = {p.value for p in PorteTomador}
    if porte not in portes_validos:
        raise PorteInvalido(
            f"Porte '{payload.porte}' fora do enquadramento da ESC "
            f"(esperado um de {sorted(portes_validos)}, LC 167/2019)"
        )

    if db.query(Tomador).filter(Tomador.cnpj == cnpj).first() is not None:
        raise TomadorDuplicado(f"Já existe tomador com CNPJ {cnpj}")

    tomador = Tomador(
        id=uuid4(),
        cnpj=cnpj,
        razao_social=payload.razao_social.strip(),
        porte=porte,
        municipio=payload.municipio.strip(),
        uf=payload.uf.strip().upper(),
        municipio_autorizado=False,
    )
    db.add(tomador)
    db.commit()
    db.refresh(tomador)
    return TomadorOut.model_validate(tomador)


@router.get("", response_model=list[TomadorOut])
def listar_tomadores(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> list[TomadorOut]:
    """Lista tomadores cadastrados. Requires: operador ou admin."""
    tomadores = db.query(Tomador).order_by(Tomador.razao_social).all()
    return [TomadorOut.model_validate(t) for t in tomadores]


@router.get("/{tomador_id}", response_model=TomadorOut)
def obter_tomador(
    tomador_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> TomadorOut:
    """Lê um tomador pelo id. Requires: operador ou admin. 404 se não existir."""
    tomador = db.query(Tomador).filter(Tomador.id == tomador_id).first()
    if tomador is None:
        raise TomadorNaoEncontrado(f"Tomador {tomador_id} não encontrado")
    return TomadorOut.model_validate(tomador)


@router.patch("/{tomador_id}/municipio-autorizado", response_model=TomadorOut)
def definir_municipio_autorizado(
    tomador_id: UUID,
    payload: MunicipioAutorizadoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> TomadorOut:
    """
    Libera ou revoga a área de atuação de um tomador (gate geográfico do
    Art. 5º). Requires: admin. Substitui o UPDATE manual via SQL por uma
    decisão de administrador explícita e passível de auditoria.
    """
    tomador = db.query(Tomador).filter(Tomador.id == tomador_id).first()
    if tomador is None:
        raise TomadorNaoEncontrado(f"Tomador {tomador_id} não encontrado")

    # updated_at é atualizado automaticamente pelo onupdate do model.
    tomador.municipio_autorizado = payload.autorizado  # type: ignore[assignment]
    db.commit()
    db.refresh(tomador)
    return TomadorOut.model_validate(tomador)
