"""012 - instrumento contratual e registro na entidade registradora.

Baseline convertido de migrations/012_contrato_e_registro.sql — ver 0001
para a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-09
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "012_contrato_e_registro.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Triggers antes das tabelas: ambos recusam DELETE, e a ordem explícita
    evita depender de o DROP TABLE ignorá-los."""
    op.execute("drop view if exists v_operacoes_sem_registro_confirmado")
    op.execute("drop trigger if exists trg_registro_transicao on registro_operacao")
    op.execute("drop function if exists fn_registro_transicao()")
    op.execute("drop table if exists registro_operacao")
    op.execute("drop view if exists v_contrato_vigente")
    op.execute("drop trigger if exists trg_contrato_imutavel on contrato_emprestimo")
    op.execute("drop function if exists fn_contrato_imutavel()")
    op.execute("drop trigger if exists trg_contrato_hash on contrato_emprestimo")
    op.execute("drop function if exists fn_contrato_hash()")
    op.execute("drop table if exists contrato_emprestimo")
