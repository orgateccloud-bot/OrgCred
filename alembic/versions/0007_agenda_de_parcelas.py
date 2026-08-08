"""007 - agenda de parcelas gerada na ativação, imutável depois.

Baseline convertido de migrations/007_agenda_de_parcelas.sql — ver 0001
para a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-06
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "007_agenda_de_parcelas.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Remove a agenda de parcelas.

    O trigger de imutabilidade precisa cair ANTES da tabela: ele recusa
    DELETE em parcela (OC009), e um DROP TABLE com o trigger ativo não
    dispara o guard, mas a ordem explícita deixa a intenção clara.
    """
    op.execute("drop trigger if exists trg_gerar_parcelas on operacao_credito")
    op.execute("drop function if exists fn_gerar_parcelas_na_ativacao()")
    op.execute("drop trigger if exists trg_parcela_imutavel on parcela")
    op.execute("drop function if exists fn_parcela_imutavel()")
    op.execute("drop function if exists fn_gerar_parcelas(uuid)")
    op.execute("drop table if exists parcela")
