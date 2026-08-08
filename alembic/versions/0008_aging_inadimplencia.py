"""008 - aging de inadimplência, transição automática e trilha de autoria.

Baseline convertido de migrations/008_aging_inadimplencia.sql — ver 0001
para a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-08
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "008_aging_inadimplencia.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    op.execute("drop function if exists fn_processar_aging(int)")
    op.execute("drop trigger if exists trg_registrar_evento_operacao on operacao_credito")
    op.execute("drop function if exists fn_registrar_evento_operacao()")
    op.execute("drop view if exists v_aging_operacoes")
    op.execute("drop function if exists fn_faixa_aging(int)")
    op.execute("drop function if exists fn_dias_atraso(uuid)")
    op.execute("drop trigger if exists trg_operacao_evento_append_only on operacao_evento")
    op.execute("drop function if exists fn_operacao_evento_append_only()")
    op.execute("drop table if exists operacao_evento")
