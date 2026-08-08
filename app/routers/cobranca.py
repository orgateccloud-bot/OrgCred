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

from decimal import Decimal
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import processar_aging
from app.core.security import get_admin_user, get_current_user
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
