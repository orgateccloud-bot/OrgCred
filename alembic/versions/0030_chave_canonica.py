"""030 - a canonização passa a valer para TODOS os campos que formam a
identidade do crédito, e não só para o que saiu dela.

A 029 tirou a conta da identidade com o argumento correto — exportações
diferentes escrevem coisas diferentes — e não fez a mesma pergunta ao FITID nem
à data. Resultado medido: 'TED1' contra 'ted1', contra '0TED1', contra 'TED 1',
e o mesmo instante exportado em BRT e em GMT, todos dobrando o lastro e
devolvendo capital ao teto do Art. 5º.

Baseline convertido de migrations/030_chave_canonica.sql. A correção da data
mora no parser (app/ofx.py::_ler_data), que descartava o fuso declarado.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-27
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Uma função nova, uma coluna gerada e as duas chaves refeitas sobre ela.

    PODE FALHAR EM BASE COM DADOS, e a falha é o sinal correto: as chaves novas
    são mais FORTES que as que substituem (unem o que a grafia do identificador
    separava). Conferir antes:

        select upper(regexp_replace(documento, '[^0-9A-Za-z]', '', 'g')) as canonico,
               valor, data_movimento, count(*), array_agg(documento), array_agg(id)
          from movimento_bancario
         group by 1, 2, 3
        having count(*) > 1;

    Cada grupo é um crédito contado mais de uma vez — e, ao contrário da 028, a
    escolha de qual linha fica é mecânica: as linhas são o MESMO crédito, com o
    identificador escrito de formas diferentes. A que não lastreia baixa nenhuma
    é a excedente:

        select m.id, m.documento, p.id as parcela_id
          from movimento_bancario m
          left join parcela p on p.movimento_id = m.id
         where m.documento_chave in (...);

    Removê-la exige desligar `trg_movimento_imutavel` (OC012) e é ato de
    operador com registro, não de migration.

    PRODUÇÃO NÃO PRECISA DISSO: roda o schema 0026 com `movimento_bancario`
    vazio, e as quatro migrations sobem de uma vez em base limpa.
    """
    sql = (_SQL_DIR / "030_chave_canonica.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Devolve as duas chaves ao `documento` verbatim e remove a coluna gerada.

    NÃO PODE FALHAR POR DADO: as chaves antigas são mais FRACAS (separam o que
    estas unem), então nenhuma linha existente as viola.

    REABRE A DUPLICAÇÃO POR GRAFIA DO IDENTIFICADOR — 'TED1' e 'ted1' voltam a
    ser dois créditos —, e o efeito de cada duplicação é capital de volta ao
    teto do Art. 5º contra dinheiro que não entrou.

    A ORDEM É OBRIGATÓRIA: as constraints dependem da coluna, e a coluna gerada
    depende da função.
    """
    op.execute("""
        alter table movimento_bancario
            drop constraint if exists movimento_credito_unico
    """)
    op.execute("""
        alter table movimento_bancario
            drop constraint if exists movimento_documento_por_conta
    """)
    # A coluna sai ANTES das funções: ela é gerada por `fn_documento_chave`, e o
    # Postgres recusa dropar uma função da qual uma coluna gerada depende.
    op.execute("alter table movimento_bancario drop column if exists documento_chave")

    op.execute("""
        alter table movimento_bancario
            add constraint movimento_credito_unico
            unique (documento, valor, data_movimento)
    """)
    op.execute("""
        alter table movimento_bancario
            add constraint movimento_documento_por_conta
            unique nulls not distinct (documento, conta_chave)
    """)

    # `fn_conta_chave` volta a embutir a normalização, para não depender de
    # `fn_chave_texto` — que sai em seguida.
    op.execute("""
        create or replace function fn_conta_chave(p_conta text)
        returns text as $$
            select nullif(
                regexp_replace(
                    upper(regexp_replace(split_part(p_conta, '/', -1), '[^0-9A-Za-z]', '', 'g')),
                    '^0+',
                    ''
                ),
                ''
            )
        $$ language sql immutable strict;
    """)
    op.execute("drop function if exists fn_documento_chave(text)")
    op.execute("drop function if exists fn_chave_texto(text)")
