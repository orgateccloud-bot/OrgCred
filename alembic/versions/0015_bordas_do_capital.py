"""015 - fecha as bordas do teto do Art. 5º (OC020, OC021 e CHECKs de domínio).

Baseline convertido de migrations/015_bordas_do_capital.sql.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "015_bordas_do_capital.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Reabre as três bordas.

    Não há SQL anterior para reexecutar: esta migration não redefiniu nenhuma
    função pré-existente (fn_check_teto_capital e fn_check_reducao_capital
    ficaram como a 014 e a 006 as deixaram), só acrescentou triggers, funções
    novas e constraints. Desfazer é derrubar o que foi acrescentado.

    Descer daqui devolve o banco ao estado em que um UPDATE em operação ativa
    e um DELETE em esc_capital_social furam o teto sem deixar rastro no
    ledger. É reversibilidade, não é segurança equivalente.
    """
    op.execute(
        "drop trigger if exists trg_bloquear_alteracao_operacao_comprometida "
        "on operacao_credito"
    )
    op.execute("drop function if exists fn_bloquear_alteracao_operacao_comprometida()")

    op.execute("drop trigger if exists trg_bloquear_update_capital_social on esc_capital_social")
    op.execute("drop trigger if exists trg_bloquear_delete_capital_social on esc_capital_social")
    op.execute("drop function if exists fn_bloquear_mutacao_capital_social()")

    op.execute(
        "alter table esc_capital_social drop constraint if exists esc_capital_social_valor_positivo"
    )
    op.execute(
        "alter table esc_capital_social "
        "drop constraint if exists esc_capital_social_tipo_evento_valido"
    )
    op.execute(
        "alter table operacao_credito "
        "drop constraint if exists operacao_credito_valor_principal_positivo"
    )
    op.execute(
        "alter table operacao_credito "
        "drop constraint if exists operacao_credito_numero_parcelas_positivo"
    )
