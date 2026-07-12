"""002 - tabela usuario com papéis (admin/operador).

Baseline convertido de migrations/002_usuarios_papeis.sql — ver 0001 para
a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "002_usuarios_papeis.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    op.execute("drop table if exists usuario")
