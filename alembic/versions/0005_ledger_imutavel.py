"""005 - integridade do capital_ledger: proteção append-only + hash-chain.

Baseline convertido de migrations/005_ledger_imutavel.sql — ver 0001 para a
justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "005_ledger_imutavel.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    op.execute("drop function if exists fn_verificar_cadeia_ledger()")
    op.execute("drop trigger if exists trg_calcular_hash_ledger on capital_ledger")
    op.execute("drop function if exists fn_calcular_hash_ledger()")
    op.execute("alter table capital_ledger drop column if exists current_hash")
    op.execute("alter table capital_ledger drop column if exists prev_hash")
    op.execute("drop trigger if exists trg_bloquear_delete_ledger on capital_ledger")
    op.execute("drop trigger if exists trg_bloquear_update_ledger on capital_ledger")
    op.execute("drop function if exists fn_bloquear_mutacao_ledger()")
