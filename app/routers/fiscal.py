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
from decimal import ROUND_HALF_UP, Decimal
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


# ---------------------------------------------------------------------
# Memória de cálculo
# ---------------------------------------------------------------------
#
# O contador recebe números prontos. Numa base tributária IMUTÁVEL (OC016), um
# número sem derivação é um número que ninguém consegue conferir nem contestar
# — e a apuração é exatamente o documento que alguém vai ter que defender.
#
# NADA AQUI CONSULTA parcela, movimento_bancario NEM parametro_fiscal. A
# memória é derivada da PRÓPRIA linha de apuracao_fiscal: as duas receitas e o
# snapshot de percentuais, alíquotas e limite que a 011 gravou dentro dela.
# Derivar do snapshot é melhor do que duplicar o dado numa tabela nova — a
# memória passa a ser reproduzível a partir da linha imutável, e a memória de
# um trimestre de 2021 sai igual hoje e daqui a cinco anos porque a entrada
# dela não pode mudar.
#
# E é justamente por reproduzir a fórmula, em vez de copiar o resultado, que a
# memória PODE DIVERGIR do gravado: se fn_apurar_trimestre mudar depois de uma
# apuração existir — foi o que a 018 fez com a 011 —, o recálculo a partir do
# mesmo snapshot dá outro número. A divergência é REPORTADA, nunca escondida.
# OC016 impede corrigir a linha, então a única providência possível é retificar
# o trimestre, e para isso é preciso enxergar o problema. Uma memória que se
# alinhasse ao gravado por construção não teria valor nenhum de conferência.
#
# O PREÇO DISSO, ESCRITO AQUI PARA NÃO SER DESCOBERTO DEPOIS: `_memoria_de` é
# uma SEGUNDA implementação da mesma fórmula, em outra linguagem. Ela não segue
# fn_apurar_trimestre sozinha. Quem alterar a função no banco tem que alterar
# esta função na mesma migration — senão a memória passa a acusar divergência
# em TODA apuração nova, e a leitura na tela ("o gravado está errado, retifique
# o trimestre") fica invertida: o desatualizado é o recálculo, e retificar não
# conserta nada. Os testes de TestMemoriaDeCalculo travam cada passo contra o
# Postgres de verdade e é neles que essa dessincronização aparece primeiro.


_CENTAVO = Decimal("0.01")


def _round2(valor: Decimal) -> Decimal:
    """Mesmo arredondamento do `round(numeric, 2)` do Postgres.

    O Postgres desempata para LONGE DO ZERO; o default do Python é
    ROUND_HALF_EVEN (arredondamento bancário). Sem esta função a memória
    acusaria divergência de um centavo em toda apuração cujo produto caísse
    exatamente na metade — alarme falso no único indicador que precisa ser
    confiável.
    """
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


class LinhaMemoriaOut(BaseModel):
    """Um tributo, do que entrou até o que saiu.

    `percentual_presuncao`, `limite` e `excedente` são nulos onde o conceito
    não existe: presunção é de IRPJ/CSLL (PIS e COFINS cumulativos incidem
    sobre a receita) e limite só faz sentido no adicional. Nulo, e não zero —
    zero seria uma presunção de 0%, que é outra afirmação.
    """

    chave: str
    tributo: str
    receita_considerada: Decimal
    percentual_presuncao: Optional[Decimal]
    base_calculo: Decimal
    limite: Optional[Decimal]
    excedente: Optional[Decimal]
    aliquota: Decimal
    valor: Decimal
    valor_gravado: Decimal
    confere: bool


class DivergenciaOut(BaseModel):
    campo: str
    rotulo: str
    calculado: Decimal
    gravado: Decimal
    diferenca: Decimal


class MemoriaCalculoOut(BaseModel):
    apuracao_id: UUID
    ano: int
    trimestre: int
    versao: int
    regime_reconhecimento: str
    receita_juros: Decimal
    receita_demais: Decimal
    receita_total: Decimal
    receita_total_gravada: Decimal
    linhas: List[LinhaMemoriaOut]
    total_tributos: Decimal
    total_tributos_gravado: Decimal
    confere: bool
    divergencias: List[DivergenciaOut]


def _linha(
    chave: str,
    tributo: str,
    receita_considerada: Decimal,
    percentual_presuncao: Optional[Decimal],
    base_calculo: Decimal,
    aliquota: Decimal,
    valor: Decimal,
    valor_gravado: Decimal,
    limite: Optional[Decimal] = None,
    excedente: Optional[Decimal] = None,
) -> LinhaMemoriaOut:
    return LinhaMemoriaOut(
        chave=chave,
        tributo=tributo,
        receita_considerada=receita_considerada,
        percentual_presuncao=percentual_presuncao,
        base_calculo=base_calculo,
        limite=limite,
        excedente=excedente,
        aliquota=aliquota,
        valor=valor,
        valor_gravado=valor_gravado,
        confere=valor == valor_gravado,
    )


def _memoria_de(r: object) -> MemoriaCalculoOut:
    """Reproduz, passo a passo, a aritmética de fn_apurar_trimestre (018).

    A ordem das contas é a da função, e não uma reescrita "equivalente":
    presunção sobre a receita total, alíquota sobre a base presumida,
    PIS/COFINS sobre a receita crua, adicional só sobre o excedente do limite
    trimestral, com arredondamento nos mesmos pontos. Duas fórmulas
    algebricamente iguais arredondam diferente — e um centavo de diferença
    faria a memória acusar erro onde não há.
    """
    receita_juros: Decimal = r.receita_juros  # type: ignore[attr-defined]
    receita_demais: Decimal = r.receita_demais  # type: ignore[attr-defined]
    receita_total_gravada: Decimal = r.receita_total  # type: ignore[attr-defined]
    # `receita_total` é coluna GERADA no banco (018) e não pode divergir — mas
    # a soma é refeita aqui do mesmo jeito, porque a memória não confere o que
    # ela própria copiou.
    receita_total = receita_juros + receita_demais

    presuncao_irpj: Decimal = r.percentual_presuncao_irpj  # type: ignore[attr-defined]
    presuncao_csll: Decimal = r.percentual_presuncao_csll  # type: ignore[attr-defined]
    aliquota_irpj: Decimal = r.aliquota_irpj  # type: ignore[attr-defined]
    aliquota_csll: Decimal = r.aliquota_csll  # type: ignore[attr-defined]
    adicional_aliquota: Decimal = r.adicional_irpj_aliquota  # type: ignore[attr-defined]
    adicional_limite: Decimal = r.adicional_irpj_limite  # type: ignore[attr-defined]
    aliquota_pis: Decimal = r.aliquota_pis  # type: ignore[attr-defined]
    aliquota_cofins: Decimal = r.aliquota_cofins  # type: ignore[attr-defined]

    base_irpj = _round2(receita_total * presuncao_irpj)
    base_csll = _round2(receita_total * presuncao_csll)

    irpj = _round2(base_irpj * aliquota_irpj)
    # O excedente NÃO é arredondado antes de entrar na multiplicação: a função
    # do banco aplica `round` uma vez só, sobre o produto.
    excedente = max(base_irpj - adicional_limite, Decimal("0"))
    adicional = _round2(excedente * adicional_aliquota)
    csll = _round2(base_csll * aliquota_csll)
    pis = _round2(receita_total * aliquota_pis)
    cofins = _round2(receita_total * aliquota_cofins)
    total = irpj + adicional + csll + pis + cofins

    linhas = [
        _linha(
            "irpj",
            "IRPJ",
            receita_total,
            presuncao_irpj,
            base_irpj,
            aliquota_irpj,
            irpj,
            r.irpj,  # type: ignore[attr-defined]
        ),
        # A linha que mais gera dúvida, e a única com limite e excedente
        # explícitos: sem eles, "adicional 0,00" parece esquecimento em vez de
        # "a base não chegou ao limite do trimestre".
        _linha(
            "adicional_irpj",
            "Adicional de IRPJ",
            receita_total,
            presuncao_irpj,
            base_irpj,
            adicional_aliquota,
            adicional,
            r.adicional_irpj,  # type: ignore[attr-defined]
            limite=adicional_limite,
            excedente=excedente,
        ),
        _linha(
            "csll",
            "CSLL",
            receita_total,
            presuncao_csll,
            base_csll,
            aliquota_csll,
            csll,
            r.csll,  # type: ignore[attr-defined]
        ),
        # PIS/COFINS cumulativos: a base É a receita. Presunção é conceito de
        # IRPJ/CSLL e vai nula aqui, não zerada.
        _linha(
            "pis",
            "PIS",
            receita_total,
            None,
            receita_total,
            aliquota_pis,
            pis,
            r.pis,  # type: ignore[attr-defined]
        ),
        _linha(
            "cofins",
            "COFINS",
            receita_total,
            None,
            receita_total,
            aliquota_cofins,
            cofins,
            r.cofins,  # type: ignore[attr-defined]
        ),
    ]

    # As bases entram na conferência junto com os tributos: base errada com
    # tributo certo é impossível, mas é a base que EXPLICA o tributo errado —
    # sem ela o contador vê a divergência e não sabe onde ela nasceu.
    candidatas: List[tuple[str, str, Decimal, Decimal]] = [
        ("receita_total", "Receita total tributada", receita_total, receita_total_gravada),
        ("base_irpj", "Base de cálculo do IRPJ", base_irpj, r.base_irpj),  # type: ignore[attr-defined]
        ("base_csll", "Base de cálculo da CSLL", base_csll, r.base_csll),  # type: ignore[attr-defined]
        *[(linha.chave, linha.tributo, linha.valor, linha.valor_gravado) for linha in linhas],
        ("total_tributos", "Total de tributos", total, r.total_tributos),  # type: ignore[attr-defined]
    ]
    divergencias = [
        DivergenciaOut(
            campo=campo,
            rotulo=rotulo,
            calculado=calculado,
            gravado=gravado,
            diferenca=calculado - gravado,
        )
        for campo, rotulo, calculado, gravado in candidatas
        if calculado != gravado
    ]

    return MemoriaCalculoOut(
        apuracao_id=r.id,  # type: ignore[attr-defined]
        ano=r.ano,  # type: ignore[attr-defined]
        trimestre=r.trimestre,  # type: ignore[attr-defined]
        versao=r.versao,  # type: ignore[attr-defined]
        regime_reconhecimento=r.regime_reconhecimento,  # type: ignore[attr-defined]
        receita_juros=receita_juros,
        receita_demais=receita_demais,
        receita_total=receita_total,
        receita_total_gravada=receita_total_gravada,
        linhas=linhas,
        total_tributos=total,
        total_tributos_gravado=r.total_tributos,  # type: ignore[attr-defined]
        confere=not divergencias,
        divergencias=divergencias,
    )


@router.get("/apuracoes/{apuracao_id}/memoria", response_model=MemoriaCalculoOut)
def get_memoria_calculo(
    apuracao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> MemoriaCalculoOut:
    """Memória de cálculo de UMA apuração, derivada do snapshot dela.

    Aberta ao operador, e não restrita ao admin: quem apura é o admin, mas
    quem CONFERE é o contador — e conferência que exige privilégio de escrita
    não é conferência.

    Busca por `id`, e não por (ano, trimestre): a retificação não apaga a
    versão anterior, e a memória da versão 1 precisa continuar acessível para
    explicar a diferença entre o que foi declarado e o que foi retificado.
    """
    row = db.execute(
        text("select * from apuracao_fiscal where id = :id"), {"id": str(apuracao_id)}
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Apuração fiscal não encontrada.")
    return _memoria_de(row)
