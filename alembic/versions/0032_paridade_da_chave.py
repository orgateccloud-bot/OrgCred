"""032 - o espelho da chave concorda em todo o Unicode: o fallback de
fn_documento_chave deixa de usar upper(), que divergia do str.upper() do Python
(ß->SS) e quebrava a paridade que a 030 prometeu.

Baseline convertido de migrations/032_paridade_da_chave.sql.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-28
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """`create or replace` de uma função IMMUTABLE que uma coluna gerada STORED
    usa. Postgres permite: a coluna já existe e mantém os valores gravados; só
    escritas futuras usam a definição nova. Nenhuma linha é reescrita, e não há
    back-fill — a diferença só aparece no fallback (FITID sem alfanumérico
    ASCII), que na prática não ocorre em extrato de banco brasileiro."""
    sql = (_SQL_DIR / "032_paridade_da_chave.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Devolve o fallback ao `upper(p_documento)` da 030 — reabre a divergência
    Python/SQL fora do ASCII. Não destrói dado."""
    op.execute("""
        create or replace function fn_documento_chave(p_documento text)
        returns text as $$
            select coalesce(fn_chave_texto(p_documento), upper(p_documento))
        $$ language sql immutable strict;
    """)
