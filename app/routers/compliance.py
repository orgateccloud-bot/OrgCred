"""
Router: compliance PLD/FT — a parte que não depende de terceiro.

O regime PLD/COAF aplicável a uma ESC ainda depende de parecer jurídico
(ver MAPEAMENTO_E_PLANO_DE_COMBATE.md, Frente 4). O que este módulo entrega
sem esperar ninguém:

- Identificação do tomador com EVIDÊNCIA ARQUIVADA e verificável por hash.
- RETENÇÃO de 5 anos garantida pelo banco (Lei 9.613/98, art. 10, III).
- DETECÇÃO INTERNA de atipicidade sobre os dados que já existem.

O canal externo é ADAPTADOR: a ocorrência já nasce com os campos
`comunicado_em`/`comunicacao_ref`, que nada preenche hoje. Quando o parecer
sair, liga-se o envio sem tocar na detecção — e o histórico já acumulado
continua válido.

NÃO IMPLEMENTADO POR SER DECISÃO DE NEGÓCIO: bloquear a ativação de
operações de tomador sem identificação arquivada. É a amarra com dentes,
mas hoje existem tomadores sem evidência e ligar o bloqueio sem aviso
pararia a operação. `GET /compliance/identificacao/pendencias` expõe a
lacuna, com o capital exposto, para a decisão ser tomada com o número.
"""

import base64
import binascii
import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/compliance", tags=["compliance"])

# Lei 9.613/98, art. 10, III — guarda por no mínimo 5 anos.
RETENCAO_ANOS = 5


# ---------------------------------------------------------------------
# Identificação com evidência arquivada
# ---------------------------------------------------------------------


class DocumentoOut(BaseModel):
    id: UUID
    tomador_id: UUID
    tipo: str
    nome_arquivo: str
    sha256: str
    arquivado_em: datetime
    retencao_ate: date


class ArquivarDocumentoIn(BaseModel):
    """O conteúdo vem em base64 apenas para que o HASH seja calculado aqui.

    O binário não é persistido: o banco guarda o hash, e o arquivo vive no
    storage. Guardar o arquivo no Postgres inflaria o banco sem acrescentar
    garantia — o que se precisa provar é que o documento apresentado depois
    é bit a bit o mesmo que foi arquivado.
    """

    tipo: Literal[
        "contrato_social",
        "cartao_cnpj",
        "documento_socio",
        "comprovante_endereco",
        "procuracao",
        "outro",
    ]
    nome_arquivo: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.get("/tomadores/{tomador_id}/documentos", response_model=List[DocumentoOut])
def get_documentos(
    tomador_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[DocumentoOut]:
    rows = db.execute(
        text("""
        select id, tomador_id, tipo, nome_arquivo, sha256, arquivado_em, retencao_ate
        from tomador_documento where tomador_id = :t order by arquivado_em desc
    """),
        {"t": str(tomador_id)},
    ).all()
    return [
        DocumentoOut(
            id=r.id,
            tomador_id=r.tomador_id,
            tipo=r.tipo,
            nome_arquivo=r.nome_arquivo,
            sha256=r.sha256,
            arquivado_em=r.arquivado_em,
            retencao_ate=r.retencao_ate,
        )
        for r in rows
    ]


@router.post("/tomadores/{tomador_id}/documentos", response_model=DocumentoOut, status_code=201)
def post_documento(
    tomador_id: UUID,
    body: ArquivarDocumentoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> DocumentoOut:
    """Arquiva a evidência de identificação.

    `retencao_ate` é gravado agora, e não calculado na leitura: se o prazo
    legal mudar, os documentos já arquivados mantêm a regra vigente à época
    — que é o que se defende numa fiscalização.
    """
    existe = db.execute(text("select 1 from tomador where id = :t"), {"t": str(tomador_id)}).first()
    if existe is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")

    try:
        row = db.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate, usuario_id)
            values (:t, :tipo, :nome, :sha, current_date + make_interval(years => :anos), :u)
            returning id, tomador_id, tipo, nome_arquivo, sha256, arquivado_em, retencao_ate
            """),
            {
                "t": str(tomador_id),
                "tipo": body.tipo,
                "nome": body.nome_arquivo,
                "sha": body.sha256,
                "anos": RETENCAO_ANOS,
                "u": str(user.id),
            },
        ).one()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Este arquivo já está arquivado para este tomador (mesmo hash).",
        ) from exc

    return DocumentoOut(
        id=row.id,
        tomador_id=row.tomador_id,
        tipo=row.tipo,
        nome_arquivo=row.nome_arquivo,
        sha256=row.sha256,
        arquivado_em=row.arquivado_em,
        retencao_ate=row.retencao_ate,
    )


class VerificacaoIn(BaseModel):
    """Conteúdo em base64 do arquivo a conferir contra o que foi arquivado."""

    conteudo_base64: str = Field(min_length=1)


class VerificacaoOut(BaseModel):
    sha256_calculado: str
    confere: bool


@router.post("/documentos/{documento_id}/verificar", response_model=VerificacaoOut)
def post_verificar_documento(
    documento_id: UUID,
    body: VerificacaoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> VerificacaoOut:
    """Confere se um arquivo é bit a bit o que foi arquivado.

    É o que dá sentido a guardar só o hash: sem esta conferência, o hash
    seria um número sem uso.
    """
    row = db.execute(
        text("select sha256 from tomador_documento where id = :d"), {"d": str(documento_id)}
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não existe.")

    try:
        conteudo = base64.b64decode(body.conteudo_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Conteúdo não é base64 válido.") from exc

    calculado = hashlib.sha256(conteudo).hexdigest()
    return VerificacaoOut(sha256_calculado=calculado, confere=calculado == row.sha256)


class PendenciaIdentificacaoOut(BaseModel):
    tomador_id: UUID
    cnpj: str
    razao_social: str
    capital_exposto: Decimal


@router.get("/identificacao/pendencias", response_model=List[PendenciaIdentificacaoOut])
def get_pendencias_identificacao(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[PendenciaIdentificacaoOut]:
    """Tomadores sem nenhuma evidência arquivada, com o capital exposto.

    Ordenado por exposição: é essa a lista que embasa a decisão de negócio
    sobre exigir identificação antes da ativação.
    """
    rows = db.execute(
        text("""
        select tomador_id, cnpj, razao_social, capital_exposto
        from v_tomadores_sem_identificacao
        order by capital_exposto desc, razao_social
    """)
    ).all()
    return [
        PendenciaIdentificacaoOut(
            tomador_id=r.tomador_id,
            cnpj=r.cnpj,
            razao_social=r.razao_social,
            capital_exposto=r.capital_exposto,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------
# Detecção interna de atipicidade
# ---------------------------------------------------------------------


class OcorrenciaOut(BaseModel):
    id: UUID
    regra: str
    severidade: str
    tomador_id: Optional[UUID]
    tomador_razao_social: Optional[str]
    operacao_id: Optional[UUID]
    detalhe: str
    comunicado_em: Optional[datetime]
    created_at: datetime


@router.get("/atipicidades", response_model=List[OcorrenciaOut])
def get_atipicidades(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[OcorrenciaOut]:
    """Ocorrências detectadas, mais graves e mais recentes primeiro."""
    rows = db.execute(
        text("""
        select o.id, o.regra, o.severidade, o.tomador_id, t.razao_social as tomador_razao_social,
               o.operacao_id, o.detalhe, o.comunicado_em, o.created_at
        from ocorrencia_atipicidade o
        left join tomador t on t.id = o.tomador_id
        order by case o.severidade when 'alta' then 0 when 'media' then 1 else 2 end,
                 o.created_at desc
    """)
    ).all()
    return [
        OcorrenciaOut(
            id=r.id,
            regra=r.regra,
            severidade=r.severidade,
            tomador_id=r.tomador_id,
            tomador_razao_social=r.tomador_razao_social,
            operacao_id=r.operacao_id,
            detalhe=r.detalhe,
            comunicado_em=r.comunicado_em,
            created_at=r.created_at,
        )
        for r in rows
    ]


class DetectarIn(BaseModel):
    limiar: Decimal = Field(default=Decimal("10000"), gt=0)
    janela_dias: int = Field(default=30, ge=1, le=365)


class DetectarOut(BaseModel):
    novas_ocorrencias: int


@router.post("/atipicidades/detectar", response_model=DetectarOut)
def post_detectar(
    body: DetectarIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> DetectarOut:
    """
    Roda a varredura de atipicidade sobre os dados existentes.

    Idempotente: a constraint `ocorrencia_unica` faz uma segunda passada no
    mesmo dia não duplicar nada. Sem isso o painel viraria ruído e o
    analista pararia de olhar — que é o pior resultado possível para um
    controle de PLD.
    """
    total = db.execute(
        text("select fn_detectar_atipicidades(:limiar, :janela)"),
        {"limiar": body.limiar, "janela": body.janela_dias},
    ).scalar_one()
    db.commit()
    return DetectarOut(novas_ocorrencias=int(total))
