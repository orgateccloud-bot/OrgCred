"""009 - baixa de recebimento amarrada a movimentação bancária.

Baseline convertido de migrations/009_baixa_de_recebimento.sql — ver 0001
para a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-08
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "009_baixa_de_recebimento.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Volta ao guard da 007 (imutabilidade sem a amarra bancária)."""
    op.execute("drop view if exists v_movimentos_disponiveis")
    op.execute("drop function if exists fn_baixar_parcela(uuid, uuid)")
    op.execute("drop index if exists idx_parcela_movimento_unico")
    op.execute("alter table parcela drop column if exists movimento_id")
    op.execute("drop trigger if exists trg_movimento_imutavel on movimento_bancario")
    op.execute("drop function if exists fn_movimento_imutavel()")
    op.execute("drop table if exists movimento_bancario")

    sql_007 = (_SQL_DIR / "007_agenda_de_parcelas.sql").read_text(encoding="utf-8")
    # Reaplica só a definição de fn_parcela_imutavel da 007; o restante da
    # 007 é idempotente (create table if not exists / create or replace).
    op.execute(sql_007)
