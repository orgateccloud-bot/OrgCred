"""
Router: régua de cobrança — aging de inadimplência.

O aging é DERIVADO da agenda de parcelas (migration 007, imutável) pela view
`v_aging_operacoes`, nunca armazenado. Uma coluna denormalizada de "dias em
atraso" envelheceria em silêncio e faria a régua decidir sobre um número
errado.

Escopo ainda pendente (não bloqueado, apenas não implementado):
- Notificação automática ao tomador (email/SMS) por faixa de atraso.
- Negativação em bureaus de crédito (Serasa/SPC) após prazo configurável.
- Baixa de recebimento amarrada a movimentação bancária.
"""

from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import baixar_parcela, processar_aging, registrar_movimento_bancario
from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/cobranca", tags=["cobranca"])


class AgingItemOut(BaseModel):
    operacao_id: UUID
    tomador_id: UUID
    tomador_razao_social: str
    status: str
    valor_principal: Decimal
    dias_atraso: int
    faixa: str
    parcelas_vencidas: int
    valor_vencido: Decimal


class AgingResumoOut(BaseModel):
    """Contagem e valor vencido por faixa, para o painel de cobrança."""

    faixa: str
    quantidade: int
    valor_vencido: Decimal


class AgingOut(BaseModel):
    limite_inadimplencia_dias: int
    resumo: List[AgingResumoOut]
    operacoes: List[AgingItemOut]


# Mesmo padrão da migration 008: 90 dias é a marca clássica de "curso
# anormal" (Res. CMN 2.682). A LC 167/2019 não fixa prazo.
LIMITE_INADIMPLENCIA_DIAS = 90

_FAIXAS = ["em_dia", "ate_30", "de_31_a_60", "de_61_a_90", "acima_de_90"]


@router.get("/aging", response_model=AgingOut)
def get_aging(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AgingOut:
    """Aging de todas as operações que comprometem capital, mais atrasadas
    primeiro."""
    rows = db.execute(
        text("""
        select operacao_id, tomador_id, tomador_razao_social, status,
               valor_principal, dias_atraso, faixa, parcelas_vencidas, valor_vencido
        from v_aging_operacoes
        order by dias_atraso desc, valor_vencido desc
    """)
    ).all()

    operacoes = [
        AgingItemOut(
            operacao_id=r.operacao_id,
            tomador_id=r.tomador_id,
            tomador_razao_social=r.tomador_razao_social,
            status=r.status,
            valor_principal=r.valor_principal,
            dias_atraso=r.dias_atraso,
            faixa=r.faixa,
            parcelas_vencidas=r.parcelas_vencidas,
            valor_vencido=r.valor_vencido,
        )
        for r in rows
    ]

    # Todas as faixas aparecem, inclusive as vazias: um painel que esconde
    # a faixa "acima de 90" quando está zerada não deixa claro se não há
    # nada lá ou se o dado não foi carregado.
    resumo = [
        AgingResumoOut(
            faixa=faixa,
            quantidade=sum(1 for o in operacoes if o.faixa == faixa),
            valor_vencido=sum(
                (o.valor_vencido for o in operacoes if o.faixa == faixa), Decimal("0")
            ),
        )
        for faixa in _FAIXAS
    ]

    return AgingOut(
        limite_inadimplencia_dias=LIMITE_INADIMPLENCIA_DIAS,
        resumo=resumo,
        operacoes=operacoes,
    )


class ProcessarAgingIn(BaseModel):
    limite_dias: int = Field(default=LIMITE_INADIMPLENCIA_DIAS, ge=1, le=3650)


class ProcessarAgingOut(BaseModel):
    transicionadas: int
    limite_dias: int


@router.post("/aging/processar", response_model=ProcessarAgingOut)
def post_processar_aging(
    body: ProcessarAgingIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> ProcessarAgingOut:
    """
    Executa a régua: 'ativa' com atraso >= limite passa a 'inadimplente'.

    Exige admin, não operador: declarar inadimplência em lote tem
    consequência jurídica e reputacional para os tomadores, e o efeito é
    irreversível sem que alguém assuma nominalmente a regularização.

    As transições ficam na trilha com `origem = 'sistema'` e autor nulo —
    o que a régua fez não é imputado a quem apertou o botão. A execução em
    si é rastreável por este endpoint estar sob autenticação de admin.

    Idempotente: rodar de novo no mesmo dia não transiciona nada, porque as
    operações já saíram de 'ativa'.
    """
    total = processar_aging(db, limite_dias=body.limite_dias)
    return ProcessarAgingOut(transicionadas=total, limite_dias=body.limite_dias)


# ---------------------------------------------------------------------
# Movimentação bancária e baixa de recebimento
# ---------------------------------------------------------------------


class MovimentoOut(BaseModel):
    id: UUID
    data_movimento: date
    valor: Decimal
    descricao: Optional[str]
    documento: str
    origem: str
    conciliado: bool


class RegistrarMovimentoIn(BaseModel):
    data_movimento: date
    valor: Decimal = Field(gt=0)
    documento: str = Field(min_length=1, max_length=255)
    descricao: Optional[str] = Field(default=None, max_length=500)


@router.get("/movimentos", response_model=List[MovimentoOut])
def get_movimentos(
    apenas_disponiveis: bool = False,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[MovimentoOut]:
    """Extrato registrado, mais recente primeiro.

    `apenas_disponiveis=true` traz só os ainda não usados em nenhuma baixa —
    é o que o diálogo de baixa consome, para não oferecer um movimento que
    o banco recusaria.
    """
    rows = db.execute(
        text("""
        select m.id, m.data_movimento, m.valor, m.descricao, m.documento, m.origem,
               exists (select 1 from parcela p where p.movimento_id = m.id) as conciliado
        from movimento_bancario m
        where :todos or not exists (select 1 from parcela p where p.movimento_id = m.id)
        order by m.data_movimento desc, m.created_at desc
    """),
        {"todos": not apenas_disponiveis},
    ).all()
    return [
        MovimentoOut(
            id=r.id,
            data_movimento=r.data_movimento,
            valor=r.valor,
            descricao=r.descricao,
            documento=r.documento,
            origem=r.origem,
            conciliado=r.conciliado,
        )
        for r in rows
    ]


@router.post("/movimentos", response_model=MovimentoOut, status_code=201)
def post_movimento(
    body: RegistrarMovimentoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> MovimentoOut:
    """Registra uma linha de extrato.

    `documento` é único: reimportar o mesmo extrato não duplica crédito nem
    permite baixar duas parcelas com o mesmo dinheiro.
    """
    movimento_id = registrar_movimento_bancario(
        db,
        data_movimento=body.data_movimento,
        valor=body.valor,
        documento=body.documento,
        descricao=body.descricao,
        usuario_id=str(user.id),
    )
    return MovimentoOut(
        id=movimento_id,
        data_movimento=body.data_movimento,
        valor=body.valor,
        descricao=body.descricao,
        documento=body.documento,
        origem="manual",
        conciliado=False,
    )


class BaixarParcelaIn(BaseModel):
    movimento_id: UUID


@router.post("/parcelas/{parcela_id}/baixar", status_code=204)
def post_baixar_parcela(
    parcela_id: UUID,
    body: BaixarParcelaIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> None:
    """
    Baixa a parcela contra um movimento bancário.

    Não existe endpoint para "só marcar como paga": sem lastro, a régua de
    inadimplência pararia de ver o atraso de uma dívida que continua em
    aberto. O banco recusa com OC011.

    A baixa é terminal — não há estorno definido (ver migration 009).
    """
    baixar_parcela(db, parcela_id, body.movimento_id)
