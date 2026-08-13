"""
Router: apuração fiscal da receita da ESC.

ESCOPO: a receita da própria ESC no LUCRO PRESUMIDO, apurada
trimestralmente. Uma ESC não pode optar pelo Simples Nacional (vedação
legal), então a escolha real era Presumido ou Real — e o Presumido apura por
trimestre, o que define o período.

AINDA BLOQUEADO: IOF-crédito. Não está determinado se incide sobre operações
de ESC nem quem arca com o custo — depende de parecer jurídico-tributário,
não de escolha técnica (ver DECISOES_PENDENTES.md). Nada aqui o antecipa.
Quando a decisão sair, o escopo pendente é: colunas `iof_valor`/`iof_pago`
em operacao_credito, cálculo por operação, e gate de ativação bloqueando
operação com IOF devido e não pago.

NENHUMA ALÍQUOTA VEM EMBUTIDA, DE PROPÓSITO. Percentuais de presunção,
alíquotas e o limite do adicional de IRPJ são matéria tributária: embutidos
no código seriam um número escolhido por quem escreveu o sistema, não pelo
contador. Sem parâmetro vigente, apurar é recusado (OC015) em vez de
devolver um valor plausível e errado.
"""

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db_errors import traduzir_erro_banco
from app.core.security import get_admin_user, get_current_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/fiscal", tags=["fiscal"])


# ---------------------------------------------------------------------
# Parâmetros
# ---------------------------------------------------------------------


class ParametroFiscalOut(BaseModel):
    id: UUID
    vigencia_inicio: date
    percentual_presuncao_irpj: Decimal
    percentual_presuncao_csll: Decimal
    aliquota_irpj: Decimal
    aliquota_csll: Decimal
    adicional_irpj_aliquota: Decimal
    adicional_irpj_limite: Decimal
    aliquota_pis: Decimal
    aliquota_cofins: Decimal
    regime_reconhecimento: str
    observacao: Optional[str]


class ParametroFiscalIn(BaseModel):
    """Percentuais em fração (0,32 = 32%), não em pontos percentuais.

    Escolha deliberada: aceitar "32" e "0,32" na mesma API é como se
    escreve um erro de duas ordens de grandeza numa base tributária. A
    validação `le=1` recusa o formato errado em vez de calcular com ele.
    """

    vigencia_inicio: date
    percentual_presuncao_irpj: Decimal = Field(ge=0, le=1)
    percentual_presuncao_csll: Decimal = Field(ge=0, le=1)
    aliquota_irpj: Decimal = Field(ge=0, le=1)
    aliquota_csll: Decimal = Field(ge=0, le=1)
    adicional_irpj_aliquota: Decimal = Field(ge=0, le=1)
    adicional_irpj_limite: Decimal = Field(ge=0)
    aliquota_pis: Decimal = Field(ge=0, le=1)
    aliquota_cofins: Decimal = Field(ge=0, le=1)
    regime_reconhecimento: Literal["caixa", "competencia"]
    observacao: Optional[str] = Field(default=None, max_length=500)


def _para_out(r: object) -> ParametroFiscalOut:
    return ParametroFiscalOut(
        id=r.id,  # type: ignore[attr-defined]
        vigencia_inicio=r.vigencia_inicio,  # type: ignore[attr-defined]
        percentual_presuncao_irpj=r.percentual_presuncao_irpj,  # type: ignore[attr-defined]
        percentual_presuncao_csll=r.percentual_presuncao_csll,  # type: ignore[attr-defined]
        aliquota_irpj=r.aliquota_irpj,  # type: ignore[attr-defined]
        aliquota_csll=r.aliquota_csll,  # type: ignore[attr-defined]
        adicional_irpj_aliquota=r.adicional_irpj_aliquota,  # type: ignore[attr-defined]
        adicional_irpj_limite=r.adicional_irpj_limite,  # type: ignore[attr-defined]
        aliquota_pis=r.aliquota_pis,  # type: ignore[attr-defined]
        aliquota_cofins=r.aliquota_cofins,  # type: ignore[attr-defined]
        regime_reconhecimento=r.regime_reconhecimento,  # type: ignore[attr-defined]
        observacao=r.observacao,  # type: ignore[attr-defined]
    )


@router.get("/parametros", response_model=List[ParametroFiscalOut])
def get_parametros(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[ParametroFiscalOut]:
    """Histórico de parâmetros, vigência mais recente primeiro."""
    rows = db.execute(text("select * from parametro_fiscal order by vigencia_inicio desc")).all()
    return [_para_out(r) for r in rows]


@router.get("/parametros/vigente", response_model=Optional[ParametroFiscalOut])
def get_parametro_vigente(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> Optional[ParametroFiscalOut]:
    """Devolve `null` quando nada foi configurado — a tela precisa
    distinguir 'não configurado' de 'erro ao carregar'."""
    row = db.execute(text("select * from v_parametro_fiscal_vigente")).first()
    return _para_out(row) if row is not None else None


@router.post("/parametros", response_model=ParametroFiscalOut, status_code=201)
def post_parametro(
    body: ParametroFiscalIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> ParametroFiscalOut:
    """Registra um conjunto de parâmetros com data de vigência.

    Vigência, e não edição de um registro único: alíquota muda por lei, e
    uma apuração de 2026 tem que continuar reproduzível com os números de
    2026.
    """
    try:
        row = db.execute(
            text("""
            insert into parametro_fiscal (
                vigencia_inicio, percentual_presuncao_irpj, percentual_presuncao_csll,
                aliquota_irpj, aliquota_csll, adicional_irpj_aliquota, adicional_irpj_limite,
                aliquota_pis, aliquota_cofins, regime_reconhecimento, observacao, usuario_id
            ) values (
                :vig, :pres_irpj, :pres_csll, :aliq_irpj, :aliq_csll,
                :adic_aliq, :adic_lim, :pis, :cofins, :regime, :obs, :u
            ) returning *
            """),
            {
                "vig": body.vigencia_inicio,
                "pres_irpj": body.percentual_presuncao_irpj,
                "pres_csll": body.percentual_presuncao_csll,
                "aliq_irpj": body.aliquota_irpj,
                "aliq_csll": body.aliquota_csll,
                "adic_aliq": body.adicional_irpj_aliquota,
                "adic_lim": body.adicional_irpj_limite,
                "pis": body.aliquota_pis,
                "cofins": body.aliquota_cofins,
                "regime": body.regime_reconhecimento,
                "obs": body.observacao,
                "u": str(user.id),
            },
        ).one()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Já existe parâmetro fiscal com vigência em {body.vigencia_inicio}.",
        ) from exc
    return _para_out(row)


# ---------------------------------------------------------------------
# Apuração
# ---------------------------------------------------------------------


class ApuracaoOut(BaseModel):
    id: UUID
    ano: int
    trimestre: int
    versao: int
    # Três linhas de receita, e não uma: `receita_juros` é o rendimento
    # CONTRATUAL da agenda (migration 007) e `receita_demais` é a mora/multa
    # efetivamente recebida — naturezas diferentes, linhas diferentes da
    # escrituração, e uma mora que cresce é indicador de inadimplência que
    # ficaria invisível diluída dentro de "receita de juros". `receita_total`
    # é a base que de fato foi tributada; vem de coluna GERADA no banco
    # (migration 018), então não há como a soma exibida divergir das parcelas.
    receita_juros: Decimal
    receita_demais: Decimal
    receita_total: Decimal
    base_irpj: Decimal
    irpj: Decimal
    adicional_irpj: Decimal
    base_csll: Decimal
    csll: Decimal
    pis: Decimal
    cofins: Decimal
    total_tributos: Decimal
    regime_reconhecimento: str


def _apuracao_out(r: object) -> ApuracaoOut:
    return ApuracaoOut(
        id=r.id,  # type: ignore[attr-defined]
        ano=r.ano,  # type: ignore[attr-defined]
        trimestre=r.trimestre,  # type: ignore[attr-defined]
        versao=r.versao,  # type: ignore[attr-defined]
        receita_juros=r.receita_juros,  # type: ignore[attr-defined]
        receita_demais=r.receita_demais,  # type: ignore[attr-defined]
        receita_total=r.receita_total,  # type: ignore[attr-defined]
        base_irpj=r.base_irpj,  # type: ignore[attr-defined]
        irpj=r.irpj,  # type: ignore[attr-defined]
        adicional_irpj=r.adicional_irpj,  # type: ignore[attr-defined]
        base_csll=r.base_csll,  # type: ignore[attr-defined]
        csll=r.csll,  # type: ignore[attr-defined]
        pis=r.pis,  # type: ignore[attr-defined]
        cofins=r.cofins,  # type: ignore[attr-defined]
        total_tributos=r.total_tributos,  # type: ignore[attr-defined]
        regime_reconhecimento=r.regime_reconhecimento,  # type: ignore[attr-defined]
    )


@router.get("/apuracoes", response_model=List[ApuracaoOut])
def get_apuracoes(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[ApuracaoOut]:
    """Última versão de cada trimestre — retificações substituem na tela,
    sem apagar o histórico no banco."""
    rows = db.execute(text("select * from v_apuracao_vigente")).all()
    return [_apuracao_out(r) for r in rows]


class ApurarIn(BaseModel):
    ano: int = Field(ge=2000, le=2200)
    trimestre: int = Field(ge=1, le=4)


@router.post("/apuracoes", response_model=ApuracaoOut, status_code=201)
def post_apurar(
    body: ApurarIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> ApuracaoOut:
    """
    Apura o trimestre com os parâmetros vigentes.

    A base é a RECEITA DE JUROS, tirada da agenda de parcelas — nunca a
    amortização, que é devolução de principal e não resultado.

    Reapurar o mesmo trimestre grava uma nova VERSÃO em vez de sobrescrever:
    retificação existe no mundo real, e editar a original apagaria o que já
    foi declarado.
    """
    try:
        apuracao_id = db.execute(
            text("select fn_apurar_trimestre(:ano, :tri, :u)"),
            {"ano": body.ano, "tri": body.trimestre, "u": str(user.id)},
        ).scalar_one()
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise traduzir_erro_banco(exc) from exc

    row = db.execute(
        text("select * from apuracao_fiscal where id = :id"), {"id": str(apuracao_id)}
    ).one()
    return _apuracao_out(row)
