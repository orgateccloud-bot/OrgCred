"""
Router: régua de cobrança — aging de inadimplência.

O aging é DERIVADO da agenda de parcelas (migration 007, imutável) pela view
`v_aging_operacoes`, nunca armazenado. Uma coluna denormalizada de "dias em
atraso" envelheceria em silêncio e faria a régua decidir sobre um número
errado.

O outro assunto deste router é o LASTRO da cobrança: movimento bancário, baixa
de parcela e importação de extrato OFX. A ordem em que as três chegaram conta a
história — a baixa amarrada a movimento (migration 009) tornou impossível dar
uma parcela por paga sem lastro; a importação de OFX (024) tornou o lastro
verificável, tirando-o da digitação. As duas juntas são o que separa "existe um
registro apontado" de "o dinheiro entrou".

Escopo ainda pendente (não bloqueado, apenas não implementado):
- Notificação automática ao tomador (email/SMS) por faixa de atraso.
- Negativação em bureaus de crédito (Serasa/SPC) após prazo configurável.

Escopo DELIBERADAMENTE AUSENTE, que é coisa diferente de pendente:
- Conciliação automática (casar movimento importado com parcela por valor e
  data). Erraria exatamente onde dói — duas parcelas de mesmo valor, pagamento
  parcial, juros de mora — e a baixa é o único ato irreversível do ciclo, sem
  estorno definido (migration 009). Amarrar crédito a parcela é ato de gente,
  com nome na trilha (`parcela.baixado_por`, migration 016).
"""

import hashlib
from datetime import date
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import (
    baixar_parcela,
    importar_extrato_ofx,
    processar_aging,
    registrar_movimento_bancario,
)
from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.models import Usuario
from app.ofx import OfxInvalido, ler_ofx


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
    # Proveniência (migration 024). Nulas em lançamento digitado, preenchidas
    # em importação de OFX — e é essa diferença que a tela precisa mostrar:
    # um movimento sem `arquivo_sha256` é palavra de operador, um com hash tem
    # arquivo arquivado atrás. Esconder a distinção na leitura desfaria o
    # trabalho de gravá-la.
    conta_origem: Optional[str] = None
    arquivo_sha256: Optional[str] = None


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
               m.conta_origem, m.arquivo_sha256,
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
            conta_origem=r.conta_origem,
            arquivo_sha256=r.arquivo_sha256,
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


# ---------------------------------------------------------------------
# Importação de extrato OFX
# ---------------------------------------------------------------------
# Os dois tetos existem pela mesma razão e não são a mesma coisa. O de BYTES
# barra o upload absurdo antes de decodificar qualquer coisa; o de TRANSAÇÕES
# barra o arquivo pequeno e patológico (um OFX de tags mínimas cabe em poucos
# bytes por linha). Sem o segundo, um arquivo de 8 MiB bem construído produziria
# um INSERT de centenas de milhares de linhas — que é justamente o "timeout
# silencioso" que este endpoint não pode ter.
#
# 8 MiB é folgado para o caso real: extrato OFX de um ano de uma ESC fica na
# casa das dezenas de KiB. 50.000 transações idem. Os dois são recusa
# EXPLÍCITA, com o número no corpo da resposta — um limite que o operador não
# consegue ler vira "o sistema não importa meu arquivo".
TAMANHO_MAXIMO_OFX_BYTES = 8 * 1024 * 1024
MAXIMO_TRANSACOES_POR_IMPORTACAO = 50_000

# `movimento_bancario.valor` é numeric(14,2): 12 dígitos antes da vírgula e 2
# depois. A coluna sai da faixa por DOIS lados, e os dois viravam 500 ou pior:
#
#  - PELO TAMANHO: um TRNAMT acima de 10^12 estoura com 22003
#    (numeric_value_out_of_range), que não está no PGCODE_MAP e voltaria como
#    500 — "erro interno" para um arquivo corrompido.
#
#  - PELA ESCALA, que é o lado silencioso e o mais grave: o Postgres não recusa
#    casa decimal a mais, ele ARREDONDA. Um TRNAMT de 10.005 seria gravado como
#    10.01 — valor diferente do que está no arquivo cujo SHA-256 fica gravado na
#    linha ao lado, que é exatamente a prova que a migration 024 existe para
#    dar. E o caso extremo quebra: 0.004 arredonda para 0.00, viola o check
#    `movimento_valor_positivo` da 009 e volta 23514 -> 500.
#
# Recusar os dois aqui, dizendo qual FITID, é a resposta útil: o arquivo do
# banco está fora do que a coluna representa, e adivinhar valor monetário é o
# que este caminho existe para não fazer.
VALOR_MAXIMO_MOVIMENTO = Decimal(10) ** 12
CASAS_DECIMAIS_MOVIMENTO = 2


def _casas_decimais(valor: Decimal) -> int:
    """Quantas casas depois da vírgula o Decimal carrega de fato.

    `as_tuple().exponent` é `int` para todo número finito e só vira `str`
    ('n', 'N', 'F') em NaN/Infinity — que `ler_ofx` já recusou na leitura
    (`is_finite`). O `isinstance` existe para o verificador de tipos, não
    porque o caminho seja alcançável. Expoente positivo (`1E+3`) é inteiro
    sem casa decimal nenhuma: zero.
    """
    expoente = valor.as_tuple().exponent
    return -expoente if isinstance(expoente, int) and expoente < 0 else 0


class ImportacaoOfxOut(BaseModel):
    """O relatório da importação. Todos os números, sempre.

    `lidas` fecha com a soma dos quatro destinos possíveis, e é essa aritmética
    que permite ao operador verificar que nenhuma linha do extrato dele se
    perdeu pelo caminho.
    """

    arquivo: str
    arquivo_sha256: str
    contas: List[str]
    lidas: int
    creditos: int
    criados: int
    ja_registrados: int
    repetidos_no_arquivo: int
    debitos_ignorados: int
    periodo_inicio: Optional[date]
    periodo_fim: Optional[date]


@router.post("/movimentos/importar-ofx", response_model=ImportacaoOfxOut)
def post_importar_ofx(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> ImportacaoOfxOut:
    """
    Importa um extrato OFX e cria os movimentos de CRÉDITO que ainda não existem.

    POR QUE ESTE ENDPOINT EXISTE, e não é conveniência de digitação: até ele, o
    único produtor de `movimento_bancario` era `POST /cobranca/movimentos` — um
    formulário que aceita data, valor e documento arbitrários. O invariante que
    a migration 009 entrega (não há parcela 'paga' sem movimento apontado) é
    ESTRUTURAL, não PROBATÓRIO: prova que existe um registro, não que o dinheiro
    entrou. Para uma ESC que se defende pela rastreabilidade do fluxo
    financeiro, a distinção é a defesa inteira. Aqui o movimento nasce dos bytes
    que o banco emitiu, com o hash desses bytes gravado ao lado (migration 024).
    O formulário manual CONTINUA existindo — extrato que não se consegue exportar
    ainda precisa de caminho —, mas agora ele é distinguível na leitura.

    HTTP 200 E NÃO 201, ao contrário de `POST /movimentos`. A resposta certa
    para uma reimportação que criou zero linhas não é "Created"; e devolver 201
    ou 200 conforme o número criado faria o cliente ramificar sobre o status
    para descobrir algo que já está no corpo. O resultado desta chamada é o
    RELATÓRIO — sempre o mesmo formato, criando ou não.

    NENHUMA PARCELA É BAIXADA. Ver a nota longa em
    `capital_engine.importar_extrato_ofx`: conciliação automática por valor erra
    onde dói (parcelas de mesmo valor, pagamento parcial, juros de mora) e a
    baixa não tem estorno. O import entrega o lastro; a amarração é ato de gente.

    OPERADOR E NÃO ADMIN: conciliar recebimento é a rotina diária de quem opera
    a carteira, e a importação não decide nada — só traz o que o banco disse.
    A escolha do papel segue a mesma régua de `POST /movimentos` (operador) e de
    `/aging/processar` (admin, porque declara inadimplência).
    """
    conteudo = arquivo.file.read(TAMANHO_MAXIMO_OFX_BYTES + 1)
    if len(conteudo) > TAMANHO_MAXIMO_OFX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Arquivo excede o limite de "
                f"{TAMANHO_MAXIMO_OFX_BYTES // (1024 * 1024)} MiB para importação de extrato."
            ),
        )
    if not conteudo:
        raise HTTPException(status_code=422, detail="Arquivo vazio não é um extrato.")

    # O hash sai dos BYTES RECEBIDOS, antes de qualquer decodificação ou
    # interpretação: é o arquivo do banco que a ESC arquiva e que o fiscal pede.
    # Hash de uma normalização nossa provaria concordância com a nossa própria
    # leitura, que não é o que se quer provar.
    sha256 = hashlib.sha256(conteudo).hexdigest()

    try:
        extrato = ler_ofx(conteudo)
    except OfxInvalido as exc:
        # 422 e não 400: a requisição está bem formada, o CONTEÚDO é que não é
        # um extrato legível. A mensagem do parser vai inteira — ela diz o que
        # falta ("transação sem FITID", "arquivo truncado"), e é o que o
        # operador leva ao gerente do banco para pedir a exportação de novo.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if len(extrato.transacoes) > MAXIMO_TRANSACOES_POR_IMPORTACAO:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Extrato com {len(extrato.transacoes)} transações excede o limite de "
                f"{MAXIMO_TRANSACOES_POR_IMPORTACAO} por importação. "
                "Divida o arquivo por período."
            ),
        )

    for transacao in extrato.transacoes:
        if abs(transacao.valor) >= VALOR_MAXIMO_MOVIMENTO:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Transação {transacao.fitid} tem valor {transacao.valor}, fora da faixa "
                    "aceita para movimento bancário — o arquivo está corrompido."
                ),
            )
        if _casas_decimais(transacao.valor) > CASAS_DECIMAIS_MOVIMENTO:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Transação {transacao.fitid} tem valor {transacao.valor}, com mais de "
                    f"{CASAS_DECIMAIS_MOVIMENTO} casas decimais — gravá-lo arredondaria o "
                    "valor do extrato, e o movimento deixaria de bater com o arquivo."
                ),
            )

    resultado = importar_extrato_ofx(
        db,
        transacoes=extrato.transacoes,
        arquivo_sha256=sha256,
        usuario_id=str(user.id),
    )

    return ImportacaoOfxOut(
        arquivo=(arquivo.filename or "extrato.ofx")[:255],
        arquivo_sha256=sha256,
        contas=list(extrato.contas),
        lidas=resultado.lidas,
        creditos=resultado.creditos,
        criados=resultado.criados,
        ja_registrados=resultado.ja_registrados,
        repetidos_no_arquivo=resultado.repetidos_no_arquivo,
        debitos_ignorados=resultado.debitos_ignorados,
        periodo_inicio=resultado.periodo_inicio,
        periodo_fim=resultado.periodo_fim,
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
