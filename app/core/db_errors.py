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
    IdentificacaoAusente,
    MovimentoImutavel,
    MunicipioNaoAutorizado,
    NovacaoForaDaTransacaoAtomica,
    ParcelaImutavel,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    RegistroTransicaoInvalida,
    TetoCapitalExcedido,
    TransicaoInvalida,
)


PGCODE_MAP: Dict[str, Type[Exception]] = {
    "OC001": TetoCapitalExcedido,
    "OC002": MunicipioNaoAutorizado,
    "OC003": TransicaoInvalida,
    "OC004": RegistroEntidadeAusente,
    "OC005": ReducaoCapitalBloqueada,
    "OC008": NovacaoForaDaTransacaoAtomica,
    "OC009": ParcelaImutavel,
    "OC011": BaixaInvalida,
    "OC012": MovimentoImutavel,
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
