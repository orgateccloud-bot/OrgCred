"""001 - schema inicial (tomador, operacao_credito, esc_capital_social,
capital_ledger) + trigger original do teto de capital (pré-hardening).

Baseline convertido do SQL raw histórico em migrations/001_initial_schema.sql
(ver ADR em alembic/README_MIGRACAO.md) — o corpo é executado via op.execute()
lendo o arquivo original, para não duplicar a fonte de verdade do schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "001_initial_schema.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    op.execute("drop trigger if exists trg_check_teto_capital on operacao_credito")
    op.execute("drop function if exists fn_check_teto_capital()")
    op.execute("drop view if exists v_capital_atual")
    op.execute("drop table if exists capital_ledger")
    op.execute("drop table if exists esc_capital_social")
    op.execute("drop table if exists operacao_credito")
    op.execute("drop table if exists tomador")
