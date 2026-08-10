"""011 - apuração fiscal da receita da ESC (Lucro Presumido).

Baseline convertido de migrations/011_apuracao_fiscal.sql — ver 0001 para a
justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-08
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "011_apuracao_fiscal.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """O trigger de imutabilidade cai antes da tabela: ele recusa qualquer
    UPDATE/DELETE, e a ordem explícita deixa a intenção clara."""
    op.execute("drop function if exists fn_apurar_trimestre(int, int, text)")
    op.execute("drop view if exists v_apuracao_vigente")
    op.execute("drop trigger if exists trg_apuracao_imutavel on apuracao_fiscal")
    op.execute("drop function if exists fn_apuracao_imutavel()")
    op.execute("drop table if exists apuracao_fiscal")
    op.execute("drop view if exists v_parametro_fiscal_vigente")
    op.execute("drop table if exists parametro_fiscal")
