"""
Tradução de SQLSTATE da classe 'OC' para exceções de domínio.

Vive aqui, e não em `capital_engine`, porque deixou de ser assunto só do
motor de capital: cobrança (OC009/OC011/OC012) e fiscal (OC015/OC016)
precisam da mesma tradução, e importar um `_nome_privado` de outro módulo
seria uma dependência que ninguém mantém.

Identificação por SQLSTATE, nunca por substring da mensagem — matching por
texto quebra em silêncio quando a mensagem do trigger muda.
"""

from typing import Dict, Optional, Type

from sqlalchemy.exc import DBAPIError

from app.core.exceptions import (
    ApuracaoImutavel,
    ApuracaoSemParametro,
    BaixaForaDeCobranca,
    BaixaInvalida,
    ContratoImutavel,
    ConviteImutavel,
    DocumentoEmRetencao,
    EventoOperacaoImutavel,
    IdentificacaoAusente,
    LedgerImutavel,
    LiquidacaoSemQuitacao,
    MovimentoImutavel,
    MunicipioNaoAutorizado,
    NovacaoForaDaTransacaoAtomica,
    NovacaoSemLastro,
    OcorrenciaImutavel,
    ParcelaForaDaEmissao,
    ParcelaImutavel,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    RegistroTransicaoInvalida,
    TetoCapitalExcedido,
    TransicaoInvalida,
)


# A tabela é o CONTRATO PÚBLICO DE ERRO do motor: um SQLSTATE da classe OC
# que não esteja aqui volta como o DBAPIError cru e o handler o devolve como
# 500 — "erro interno" para uma recusa de regra de negócio perfeitamente
# prevista, que o operador não tem como interpretar e o suporte investiga
# como incidente. OC007, OC010, OC013 e OC014 estavam nesse estado: os quatro
# são levantados por triggers desde as migrations 005, 008 e 010, e nenhum
# tinha tradução.
#
# BURACOS QUE PERMANECEM DE PROPÓSITO: OC006 está reservado (gate de IOF, ver
# DECISOES_PENDENTES.md) e não existe no banco; OC020 e OC021 (migration 015)
# só são alcançáveis por SQL direto — nenhum endpoint altera operação
# comprometida nem mexe em esc_capital_social por UPDATE/DELETE —, e mapeá-los
# criaria uma mensagem de UI para um caminho que a UI não tem. Se algum dia um
# endpoint os alcançar, entram aqui junto.
#
# OC023 (migration 025) é mais um buraco de propósito: a trilha de execução
# das rotinas é append-only e nenhum endpoint a edita — o SQLSTATE só sai por
# SQL direto.
#
# OC022 (migration 017) é o contraexemplo que justifica o critério acima: ele
# NASCE alcançável pela UI — `POST /operacoes/{id}/liquidar` é o caminho de
# frente para pedi-lo — e sem tradução o operador que tentasse liquidar uma
# operação com parcelas em aberto receberia 500 no lugar da única instrução
# que resolve o caso ("baixe as parcelas contra o extrato, ou assuma o
# prejuízo pela baixa como prejuízo").
#
# OC024 (migration 026) entra pelo mesmo motivo, e por DUAS portas de frente:
# `POST /operacoes/{id}/renegociar` recusa a substituta que não cobre o saldo
# devedor da original, e `POST /operacoes/{id}/ativar` recusa a substituta que
# ficou menor depois de criada ou cuja original já saiu do comprometido. Sem
# tradução, a recusa mais importante do ciclo de renegociação chegaria como
# 500 — e o operador ficaria sem as três saídas que a mensagem carrega
# (aumentar a substituta, baixar parcelas antes de renegociar, ou encerrar
# pela baixa como prejuízo).
#
# OC025 (migration 027) é o caso limítrofe do critério, e entra — com a razão
# escrita para que a exceção não vire precedente frouxo. Nenhum endpoint insere
# parcela: a agenda é escrita só por `fn_gerar_parcelas`, de dentro do trigger
# de ativação, o que à primeira vista o colocaria ao lado de OC020/OC021 como
# buraco deliberado. A diferença é que a guarda dele fica no caminho de um
# endpoint que EXISTE — `POST /operacoes/{id}/ativar` insere a agenda inteira
# por baixo, e uma parcela recusada ali (agenda já emitida, número acima do
# contratado) sobe pela mesma pilha. Sem tradução, o operador que ativasse uma
# operação em estado inesperado receberia 500 no ato mais importante do ciclo.
PGCODE_MAP: Dict[str, Type[Exception]] = {
    "OC001": TetoCapitalExcedido,
    "OC002": MunicipioNaoAutorizado,
    "OC003": TransicaoInvalida,
    "OC004": RegistroEntidadeAusente,
    "OC005": ReducaoCapitalBloqueada,
    "OC007": LedgerImutavel,
    "OC008": NovacaoForaDaTransacaoAtomica,
    "OC009": ParcelaImutavel,
    "OC010": EventoOperacaoImutavel,
    "OC011": BaixaInvalida,
    "OC012": MovimentoImutavel,
    "OC013": DocumentoEmRetencao,
    "OC014": OcorrenciaImutavel,
    "OC015": ApuracaoSemParametro,
    "OC016": ApuracaoImutavel,
    "OC017": ContratoImutavel,
    "OC018": RegistroTransicaoInvalida,
    "OC019": IdentificacaoAusente,
    "OC022": LiquidacaoSemQuitacao,
    "OC024": NovacaoSemLastro,
    "OC025": ParcelaForaDaEmissao,
    "OC026": BaixaForaDeCobranca,
    "OC027": ConviteImutavel,
}


def extrair_sqlstate(exc: DBAPIError) -> Optional[str]:
    """
    Extrai o código SQLSTATE da exceção original do driver.

    psycopg3 (o driver em uso — ver pyproject.toml) expõe via `.sqlstate`;
    psycopg2 expunha via `.pgcode`. Checa ambos para não quebrar em silêncio
    se o driver mudar de novo — um bug real desta natureza (só `.pgcode`) já
    vazou para produção quando o projeto migrou de psycopg2 para psycopg3.
    """
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def traduzir_erro_banco(exc: DBAPIError) -> Exception:
    """Converte o erro do driver na exceção de domínio correspondente.

    Erro sem SQLSTATE mapeado volta como veio: engolir um erro
    desconhecido e devolver 422 esconderia falha de infraestrutura atrás de
    uma mensagem de regra de negócio.
    """
    sqlstate = extrair_sqlstate(exc)
    exc_cls = PGCODE_MAP.get(sqlstate) if sqlstate else None
    msg = str(getattr(exc, "orig", exc)).splitlines()[0]
    if exc_cls:
        return exc_cls(msg)
    return exc
