"""006 - novação atômica + inadimplente comprometendo capital.

Baseline convertido de migrations/006_novacao_e_inadimplencia.sql — ver 0001
para a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-06
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "006_novacao_e_inadimplencia.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Volta ao trigger da 004 e à redução da 003.

    Reaplica os arquivos anteriores (que usam CREATE OR REPLACE) e remove o
    que a 006 acrescentou. Atenção: voltar significa reabrir os dois furos
    de teto que esta migration fechou — inadimplente e renegociada
    liberavam capital sem evento no ledger.
    """
    op.execute("drop function if exists fn_novar_operacao(uuid, numeric, numeric, text, int, text)")

    # fn_check_reducao_capital volta à definição da 003; fn_check_teto_capital
    # à da 004 (a 004 já a redefine por completo).
    for arquivo in ("003_hardening_capital.sql", "004_auditoria_autor.sql"):
        op.execute((_SQL_DIR / arquivo).read_text(encoding="utf-8"))

    op.execute("drop index if exists idx_operacao_substitui")
    op.execute(
        "alter table operacao_credito drop constraint if exists nao_substitui_a_si_mesma"
    )
    op.execute("alter table operacao_credito drop column if exists substitui_operacao_id")
