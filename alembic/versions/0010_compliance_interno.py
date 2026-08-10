"""010 - compliance PLD/FT interno: identificação, retenção e atipicidade.

Baseline convertido de migrations/010_compliance_interno.sql — ver 0001
para a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-08
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "010_compliance_interno.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Derruba os triggers ANTES das tabelas.

    `trg_documento_retencao` recusa DELETE dentro do prazo legal e
    `trg_ocorrencia_append_only` recusa qualquer DELETE: sem cair primeiro,
    um downgrade que tentasse limpar linhas esbarraria nos próprios guards.
    """
    op.execute("drop function if exists fn_detectar_atipicidades(numeric, int)")
    op.execute("drop trigger if exists trg_ocorrencia_append_only on ocorrencia_atipicidade")
    op.execute("drop function if exists fn_ocorrencia_append_only()")
    op.execute("drop table if exists ocorrencia_atipicidade")
    op.execute("drop view if exists v_tomadores_sem_identificacao")
    op.execute("drop trigger if exists trg_documento_retencao on tomador_documento")
    op.execute("drop function if exists fn_documento_retencao()")
    op.execute("drop table if exists tomador_documento")
