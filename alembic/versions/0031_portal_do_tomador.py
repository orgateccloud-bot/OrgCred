"""031 - o portal do tomador: papel 'tomador', vínculo usuario.tomador_id com
CHECK de coerência, e a trilha append-only de convites (OC027).

O tomador passa a ter login próprio, que enxerga só a operação dele. O vínculo
login<->tomador é de identidade, então é o banco que garante sua coerência: um
tomador tem vínculo, um operador não tem, e o estado incoerente é recusado.

Baseline convertido de migrations/031_portal_do_tomador.sql.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-28
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Uma coluna, dois CHECKs, uma tabela de trilha e suas guardas.

    APLICA EM BASE COM DADOS sem risco de dado: `tomador_id` nasce NULO, e todo
    `usuario` existente é admin ou operador — o CHECK de coerência exige
    exatamente tomador_id NULO para esses papéis, então nenhuma linha viola.
    """
    sql = (_SQL_DIR / "031_portal_do_tomador.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Remove o portal. Não é destrutivo além de apagar a trilha de convites, o
    que só se faz sabendo que ela é prova de conformidade.

    A ordem: primeiro as guardas e a tabela de convites, depois o CHECK e a
    coluna. `usuario_papel_valido` volta a proibir 'tomador' — se ainda houver
    login de tomador, o ADD CONSTRAINT falha, o que é o sinal correto: descer
    daqui com tomadores ativos os deixaria órfãos.
    """
    op.execute("drop trigger if exists trg_bloquear_truncate_convite on convite_portal")
    op.execute("drop trigger if exists trg_convite_portal_imutavel on convite_portal")
    op.execute("drop function if exists fn_convite_portal_imutavel()")
    op.execute("drop table if exists convite_portal")

    op.execute("alter table usuario drop constraint if exists usuario_papel_vinculo_coerente")
    op.execute("drop index if exists idx_usuario_tomador")
    op.execute("alter table usuario drop column if exists tomador_id")

    op.execute("alter table usuario drop constraint if exists usuario_papel_valido")
    op.execute("""
        alter table usuario
            add constraint usuario_papel_valido check (papel in ('admin', 'operador'))
    """)
