"""Router: ciclo de vida de operações de crédito."""

from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import (
    ativar_operacao,
    criar_operacao,
    novar_operacao,
    transicionar_operacao,
)
from app.core.exceptions import OperacaoNaoEncontrada
from app.core.security import get_current_user, get_operador_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/operacoes", tags=["operacoes"])


class AtivarOperacaoOut(BaseModel):
    id: UUID
    status: str
    valor_principal: Decimal


class OperacaoListItemOut(BaseModel):
    id: UUID
    tomador_razao_social: str
    tipo: str
    valor_principal: Decimal
    numero_parcelas: int
    status: str
    created_at: datetime


@router.get("", response_model=List[OperacaoListItemOut])
def get_operacoes(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[OperacaoListItemOut]:
    """
    Lista operações de crédito, mais recentes primeiro.

    Sem paginação: o volume real (dezenas de operações, não milhares) não
    justifica a complexidade — reavaliar se o volume crescer muito.
    """
    rows = db.execute(
        text("""
        select
            oc.id, t.razao_social as tomador_razao_social, oc.tipo,
            oc.valor_principal, oc.numero_parcelas, oc.status, oc.created_at
        from operacao_credito oc
        join tomador t on t.id = oc.tomador_id
        order by oc.created_at desc
    """)
    ).all()
    return [
        OperacaoListItemOut(
            id=row.id,
            tomador_razao_social=row.tomador_razao_social,
            tipo=row.tipo,
            valor_principal=row.valor_principal,
            numero_parcelas=row.numero_parcelas,
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]


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
      - 422: Regra de negócio violada (teto, município, registro, capital) —
        RegraNegocioViolada não é capturada aqui de propósito: propaga para
        o exception_handler global (app/main.py), que produz o mesmo
        formato {"detail": "...", "codigo": "..."} usado por todo o resto
        da API. Uma versão anterior capturava localmente e aninhava o
        payload sob "detail" (formato diferente, só neste endpoint) — bug
        real encontrado via teste E2E (frontend/e2e/ativacao.spec.ts): o
        dicionário de erro do cliente esperava o formato plano e exibia
        "[object Object]" em vez da mensagem traduzida.
    """
    try:
        op = ativar_operacao(db, operacao_id, usuario_id=str(user.id))
    except OperacaoNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return AtivarOperacaoOut(
        id=op.id,  # type: ignore[arg-type]
        status=op.status,  # type: ignore[arg-type]
        valor_principal=op.valor_principal,  # type: ignore[arg-type]
    )


class TomadorResumoOut(BaseModel):
    id: UUID
    razao_social: str
    cnpj: str
    municipio: str
    uf: str
    municipio_autorizado: bool


class LedgerEventoResumoOut(BaseModel):
    id: UUID
    evento_tipo: str
    valor: Decimal
    saldo_disponivel_pos: Decimal
    usuario_nome: Optional[str]
    created_at: datetime


class OperacaoDetailOut(BaseModel):
    id: UUID
    tomador: TomadorResumoOut
    tipo: str
    valor_principal: Decimal
    taxa_juros_mensal: Decimal
    sistema_amortizacao: str
    numero_parcelas: int
    status: str
    registro_entidade_ref: Optional[str]
    created_at: datetime
    updated_at: datetime
    eventos: List[LedgerEventoResumoOut]


class CriarOperacaoIn(BaseModel):
    tomador_id: UUID
    tipo: Literal["emprestimo", "financiamento"]
    valor_principal: Decimal = Field(gt=0)
    taxa_juros_mensal: Decimal = Field(ge=0)
    sistema_amortizacao: Literal["PRICE", "SAC"]
    numero_parcelas: int = Field(gt=0)


class RegistrarOperacaoIn(BaseModel):
    registro_entidade_ref: str = Field(min_length=1, max_length=255)


class OperacaoStatusOut(BaseModel):
    id: UUID
    status: str


@router.get("/{operacao_id}", response_model=OperacaoDetailOut)
def get_operacao(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> OperacaoDetailOut:
    """Detalhe completo: dados da operação, tomador e a timeline de eventos
    do ledger ligados a ela (autor resolvido como em GET /auditoria)."""
    row = db.execute(
        text("""
        select
            oc.id, oc.tipo, oc.valor_principal, oc.taxa_juros_mensal,
            oc.sistema_amortizacao, oc.numero_parcelas, oc.status,
            oc.registro_entidade_ref, oc.created_at, oc.updated_at,
            t.id as tomador_id, t.razao_social, t.cnpj, t.municipio, t.uf,
            t.municipio_autorizado
        from operacao_credito oc
        join tomador t on t.id = oc.tomador_id
        where oc.id = :operacao_id
    """),
        {"operacao_id": str(operacao_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Operação {operacao_id} não existe.")

    eventos = db.execute(
        text("""
        select cl.id, cl.evento_tipo, cl.valor, cl.saldo_disponivel_pos,
               u.nome as usuario_nome, cl.created_at
        from capital_ledger cl
        left join usuario u on u.id::text = cl.usuario_id
        where cl.operacao_id = :operacao_id
        order by cl.created_at asc
    """),
        {"operacao_id": str(operacao_id)},
    ).all()

    return OperacaoDetailOut(
        id=row.id,
        tomador=TomadorResumoOut(
            id=row.tomador_id,
            razao_social=row.razao_social,
            cnpj=row.cnpj,
            municipio=row.municipio,
            uf=row.uf,
            municipio_autorizado=row.municipio_autorizado,
        ),
        tipo=row.tipo,
        valor_principal=row.valor_principal,
        taxa_juros_mensal=row.taxa_juros_mensal,
        sistema_amortizacao=row.sistema_amortizacao,
        numero_parcelas=row.numero_parcelas,
        status=row.status,
        registro_entidade_ref=row.registro_entidade_ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
        eventos=[
            LedgerEventoResumoOut(
                id=e.id,
                evento_tipo=e.evento_tipo,
                valor=e.valor,
                saldo_disponivel_pos=e.saldo_disponivel_pos,
                usuario_nome=e.usuario_nome,
                created_at=e.created_at,
            )
            for e in eventos
        ],
    )


@router.post("", response_model=OperacaoStatusOut, status_code=201)
def post_criar_operacao(
    body: CriarOperacaoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoStatusOut:
    """Cria a operação em 'proposta'. Não compromete capital — teto e gate
    geográfico só são validados (pelo trigger) na ativação."""
    op = criar_operacao(
        db,
        tomador_id=body.tomador_id,
        tipo=body.tipo,
        valor_principal=body.valor_principal,
        taxa_juros_mensal=body.taxa_juros_mensal,
        sistema_amortizacao=body.sistema_amortizacao,
        numero_parcelas=body.numero_parcelas,
    )
    return OperacaoStatusOut(id=op.id, status=op.status)  # type: ignore[arg-type]


def _transicao(
    db: Session,
    operacao_id: UUID,
    novo_status: str,
    user: Usuario,
    registro_entidade_ref: Optional[str] = None,
) -> OperacaoStatusOut:
    """Erros OC003 (transição inválida) etc. propagam para o handler global,
    mesmo contrato de erro do restante da API (ver docstring do ativar)."""
    try:
        op = transicionar_operacao(
            db,
            operacao_id,
            novo_status,
            usuario_id=str(user.id),
            registro_entidade_ref=registro_entidade_ref,
        )
    except OperacaoNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return OperacaoStatusOut(id=op.id, status=op.status)  # type: ignore[arg-type]


@router.post("/{operacao_id}/registrar", response_model=OperacaoStatusOut)
def post_registrar_operacao(
    operacao_id: UUID,
    body: RegistrarOperacaoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoStatusOut:
    """proposta -> registrada, gravando a referência do registro na entidade
    registradora (exigida pelo trigger OC004 na futura ativação)."""
    return _transicao(db, operacao_id, "registrada", user, body.registro_entidade_ref)


@router.post("/{operacao_id}/liquidar", response_model=OperacaoStatusOut)
def post_liquidar_operacao(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoStatusOut:
    """ativa/inadimplente -> liquidada; o trigger devolve o capital e grava
    o evento 'liquidacao' no ledger."""
    return _transicao(db, operacao_id, "liquidada", user)


@router.post("/{operacao_id}/cancelar", response_model=OperacaoStatusOut)
def post_cancelar_operacao(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoStatusOut:
    """proposta/registrada -> cancelada (o trigger rejeita cancelar 'ativa')."""
    return _transicao(db, operacao_id, "cancelada", user)


class NovarOperacaoIn(BaseModel):
    """Condições da operação SUBSTITUTA."""

    valor_principal: Decimal = Field(gt=0)
    taxa_juros_mensal: Decimal = Field(ge=0)
    sistema_amortizacao: Literal["PRICE", "SAC"]
    numero_parcelas: int = Field(gt=0)
    registro_entidade_ref: Optional[str] = Field(default=None, max_length=255)


class NovacaoOut(BaseModel):
    operacao_original_id: UUID
    operacao_substituta_id: UUID
    status_substituta: str


@router.post("/{operacao_id}/renegociar", response_model=NovacaoOut)
def post_renegociar_operacao(
    operacao_id: UUID,
    body: NovarOperacaoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> NovacaoOut:
    """
    Renegocia por novação atômica: baixa a original e cria a substituta na
    mesma transação, sob o mesmo advisory lock do teto.

    Não existe endpoint para "só marcar como renegociada": fazer a baixa sem
    amarrar a substituta deixa a original fora do comprometido e nada
    impediria criar a substituta depois, contando o capital duas vezes em
    janelas diferentes (o banco recusa com OC008).

    A substituta nasce em 'registrada' — ainda não compromete capital, e
    ativá-la passa pelos gates normais.
    """
    nova = novar_operacao(
        db,
        operacao_id,
        valor_principal=body.valor_principal,
        taxa_juros_mensal=body.taxa_juros_mensal,
        sistema_amortizacao=body.sistema_amortizacao,
        numero_parcelas=body.numero_parcelas,
        registro_entidade_ref=body.registro_entidade_ref,
        usuario_id=str(user.id),
    )
    return NovacaoOut(
        operacao_original_id=operacao_id,
        operacao_substituta_id=nova.id,  # type: ignore[arg-type]
        status_substituta=nova.status,  # type: ignore[arg-type]
    )


@router.post("/{operacao_id}/marcar-inadimplente", response_model=OperacaoStatusOut)
def post_marcar_inadimplente(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> OperacaoStatusOut:
    """ativa -> inadimplente (reversível: inadimplente -> ativa via /ativar)."""
    return _transicao(db, operacao_id, "inadimplente", user)
