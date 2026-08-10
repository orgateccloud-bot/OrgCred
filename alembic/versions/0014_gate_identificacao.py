"""014 - ativar exige identificação do tomador com evidência arquivada.

Baseline convertido de migrations/014_gate_identificacao.sql.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-09
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "014_gate_identificacao.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Volta ao gate da 013: registro confirmado sim, identificação não."""
    sql_013 = (_SQL_DIR / "013_gate_registro_confirmado.sql").read_text(encoding="utf-8")
    op.execute(sql_013)
