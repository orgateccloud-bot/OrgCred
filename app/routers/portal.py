"""Router: o portal do tomador — o cliente da ESC vendo só o que é dele.

DUAS REGRAS, e as duas são de segurança, não de conveniência:

1. TODA consulta é cercada por `where ... tomador_id = :tomador_id`, com o
   `tomador_id` vindo do usuário autenticado (`get_tomador_user`), NUNCA de um
   parâmetro da requisição. Um tomador não pode nomear a empresa que quer ver;
   ele só vê a sua, porque o filtro é o vínculo do login. Este é o análogo, na
   aplicação, do "o banco decide": o escopo não é uma opção que o cliente passa,
   é um fato do seu login.

2. Operação que não é do tomador responde 404, não 403. 403 confirmaria que a
   operação EXISTE — e a existência de uma operação de crédito de outra empresa
   já é informação que não é dele. Para o portal, o que não é seu simplesmente
   não está lá.

O portal é SOMENTE LEITURA. O tomador acompanha; quem age — ativa, baixa,
renegocia — é a ESC, pelo painel. Não há um único verbo de escrita aqui, e é
deliberado: dar ao cliente um botão que muda o estado do crédito dele seria
mover uma decisão do credor para o devedor.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_tomador_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/portal", tags=["portal"])


class PerfilTomadorOut(BaseModel):
    """Quem o tomador é, do ponto de vista dele. Não expõe nada da ESC nem de
    outro tomador — só a própria ficha e uma contagem das próprias operações."""

    tomador_id: UUID
    razao_social: str
    cnpj: str
    municipio: str
    uf: str
    operacoes_ativas: int
    operacoes_total: int


class OperacaoPortalOut(BaseModel):
    id: UUID
    tipo: str
    valor_principal: Decimal
    taxa_juros_mensal: Decimal
    sistema_amortizacao: str
    numero_parcelas: int
    status: str
    created_at: datetime
    # Quanto ainda falta pagar, somado pelo banco: parcelas em aberto. É o
    # número que o tomador procura ao abrir o portal, e recalculá-lo no cliente
    # abriria espaço para divergir do que a ESC cobra.
    parcelas_pagas: int
    saldo_em_aberto: Decimal


class ParcelaPortalOut(BaseModel):
    numero: int
    vencimento: date
    valor_total: Decimal
    status: str
    # A data em que a ESC deu a parcela por paga. Sem valor de lastro nem
    # documento bancário: o tomador vê que consta como paga e quando, não a
    # conciliação interna da ESC.
    pago_em: Optional[datetime]


class AgendaPortalOut(BaseModel):
    operacao_id: UUID
    sistema_amortizacao: str
    total_geral: Decimal
    parcelas: List[ParcelaPortalOut]


class ContratoPortalOut(BaseModel):
    """A prova de que o contrato que o tomador tem em mãos é o que a ESC emitiu.

    Expõe o SHA-256 e a versão para o tomador CONFERIR a via dele, não o corpo:
    ele já tem uma via do documento (é o que a imutabilidade do contrato, OC017,
    existe para preservar), e reservir o corpo pelo portal só multiplicaria
    cópias sem acrescentar prova.
    """

    operacao_id: UUID
    versao: int
    sha256: str
    emitido_em: datetime


def _operacao_do_tomador(db: Session, operacao_id: UUID, tomador_id: UUID) -> None:
    """Confirma que a operação é do tomador, ou 404.

    Extraído porque três rotas dependem dele e a consistência entre elas É a
    segurança: se uma esquecer o cerco, vaza. Uma função, um lugar para conferir.
    """
    dono = db.execute(
        text("select 1 from operacao_credito where id = :id and tomador_id = :t"),
        {"id": str(operacao_id), "t": str(tomador_id)},
    ).first()
    if dono is None:
        # 404 e não 403: ver o cabeçalho do módulo. O que não é seu não está lá.
        raise HTTPException(status_code=404, detail="Operação não encontrada.")


@router.get("/perfil", response_model=PerfilTomadorOut)
def get_perfil(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_tomador_user),
) -> PerfilTomadorOut:
    row = db.execute(
        text("""
        select t.id, t.razao_social, t.cnpj, t.municipio, t.uf,
               count(oc.id) filter (where oc.status in ('ativa', 'inadimplente')) as ativas,
               count(oc.id) as total
          from tomador t
          left join operacao_credito oc on oc.tomador_id = t.id
         where t.id = :t
         group by t.id, t.razao_social, t.cnpj, t.municipio, t.uf
        """),
        {"t": str(user.tomador_id)},
    ).first()
    if row is None:
        # O CHECK do banco garante o vínculo, mas o tomador pode ter sido
        # removido depois do login criado. Fail-closed com a mesma mensagem.
        raise HTTPException(status_code=404, detail="Cadastro não encontrado.")
    return PerfilTomadorOut(
        tomador_id=row.id,
        razao_social=row.razao_social,
        cnpj=row.cnpj,
        municipio=row.municipio,
        uf=row.uf,
        operacoes_ativas=row.ativas,
        operacoes_total=row.total,
    )


@router.get("/operacoes", response_model=List[OperacaoPortalOut])
def get_operacoes(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_tomador_user),
) -> List[OperacaoPortalOut]:
    rows = db.execute(
        text("""
        select oc.id, oc.tipo, oc.valor_principal, oc.taxa_juros_mensal,
               oc.sistema_amortizacao, oc.numero_parcelas, oc.status, oc.created_at,
               count(p.id) filter (where p.status = 'paga') as pagas,
               coalesce(sum(p.valor_total) filter (where p.status <> 'paga'), 0) as em_aberto
          from operacao_credito oc
          left join parcela p on p.operacao_id = oc.id
         where oc.tomador_id = :t
         group by oc.id
         order by oc.created_at desc
        """),
        {"t": str(user.tomador_id)},
    ).all()
    return [
        OperacaoPortalOut(
            id=r.id,
            tipo=r.tipo,
            valor_principal=r.valor_principal,
            taxa_juros_mensal=r.taxa_juros_mensal,
            sistema_amortizacao=r.sistema_amortizacao,
            numero_parcelas=r.numero_parcelas,
            status=r.status,
            created_at=r.created_at,
            parcelas_pagas=r.pagas,
            saldo_em_aberto=r.em_aberto,
        )
        for r in rows
    ]


@router.get("/operacoes/{operacao_id}/parcelas", response_model=AgendaPortalOut)
def get_parcelas(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_tomador_user),
) -> AgendaPortalOut:
    _operacao_do_tomador(db, operacao_id, user.tomador_id)  # type: ignore[arg-type]

    op = db.execute(
        text("select sistema_amortizacao from operacao_credito where id = :id"),
        {"id": str(operacao_id)},
    ).first()
    rows = db.execute(
        text("""
        select p.numero, p.vencimento, p.valor_total, p.status, p.pago_em
          from parcela p
         where p.operacao_id = :id
         order by p.numero asc
        """),
        {"id": str(operacao_id)},
    ).all()
    parcelas = [
        ParcelaPortalOut(
            numero=r.numero,
            vencimento=r.vencimento,
            valor_total=r.valor_total,
            status=r.status,
            pago_em=r.pago_em,
        )
        for r in rows
    ]
    return AgendaPortalOut(
        operacao_id=operacao_id,
        sistema_amortizacao=op.sistema_amortizacao,  # type: ignore[union-attr]
        total_geral=sum((p.valor_total for p in parcelas), Decimal("0")),
        parcelas=parcelas,
    )


@router.get("/operacoes/{operacao_id}/contrato", response_model=Optional[ContratoPortalOut])
def get_contrato(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_tomador_user),
) -> Optional[ContratoPortalOut]:
    _operacao_do_tomador(db, operacao_id, user.tomador_id)  # type: ignore[arg-type]

    # A versão vigente (a maior). Operação sem contrato emitido devolve null —
    # a operação existe e a ausência de contrato é um estado legítimo (ainda não
    # foi emitido), não um erro.
    row = db.execute(
        text("""
        select operacao_id, versao, sha256, emitido_em
          from contrato_emprestimo
         where operacao_id = :id
         order by versao desc
         limit 1
        """),
        {"id": str(operacao_id)},
    ).first()
    if row is None:
        return None
    return ContratoPortalOut(
        operacao_id=row.operacao_id,
        versao=row.versao,
        sha256=row.sha256,
        emitido_em=row.emitido_em,
    )
