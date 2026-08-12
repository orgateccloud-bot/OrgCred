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
    BaixaInvalida,
    ContratoImutavel,
    DocumentoEmRetencao,
    EventoOperacaoImutavel,
    IdentificacaoAusente,
    LedgerImutavel,
    MovimentoImutavel,
    MunicipioNaoAutorizado,
    NovacaoForaDaTransacaoAtomica,
    OcorrenciaImutavel,
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
