"""003 - hardening do motor de capital (F1 race condition, F2 redução de
capital vigiada, F3 máquina de estados) — ver REVISAO_2026-07-11.md.

Baseline convertido de migrations/003_hardening_capital.sql. Substitui via
CREATE OR REPLACE apenas o corpo de fn_check_teto_capital() (o trigger já
existe desde a 0001) e adiciona o trigger de redução de capital.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "003_hardening_capital.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    op.execute("drop trigger if exists trg_check_reducao_capital on esc_capital_social")
    op.execute("drop function if exists fn_check_reducao_capital()")
    # fn_check_teto_capital() volta a ter o corpo pré-hardening (definido em
    # 0001) apenas se essa revisão for re-executada; downgrade não reverte
    # automaticamente o CREATE OR REPLACE — reaplique 0001 manualmente se
    # precisar da versão sem lock (não recomendado fora de teste local).
