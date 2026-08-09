"""013 - o gate do Art. 5º §3º passa a exigir registro CONFIRMADO.

Baseline convertido de migrations/013_gate_registro_confirmado.sql.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-09
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "013_gate_registro_confirmado.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Volta ao gate de texto livre, reaplicando a definição da 006.

    A 006 é idempotente para este fim: além de `create or replace` na
    função, só faz `add column if not exists` e `create ... if not exists`.
    """
    sql_006 = (_SQL_DIR / "006_novacao_e_inadimplencia.sql").read_text(encoding="utf-8")
    op.execute(sql_006)
