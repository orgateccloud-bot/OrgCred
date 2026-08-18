"""025 - trilha append-only `execucao_rotina`: cada execução das rotinas
periódicas (aging, atipicidades, backup, restore_test) passa a se registrar no
banco, com carimbo escrito pelo próprio banco (OC023).

Baseline convertido de migrations/025_registro_de_execucao.sql.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-18
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Uma tabela nova, três triggers, nenhum dado existente tocado.

    O UPGRADE É SEGURO EM BASE COM DADOS porque não há base com dados: a tabela
    nasce agora e nenhuma outra é alterada. Não há back-fill possível — as
    execuções que já aconteceram não deixaram rastro em lugar nenhum, e é
    exatamente esse o defeito que esta migration corrige.

    O QUE ESPERAR NA PRIMEIRA HORA DEPOIS DE SUBIR, para ninguém tratar como
    incidente: a tabela sobe VAZIA, e o endpoint de estado responde
    honestamente que nunca viu nenhuma das quatro rotinas rodar. O dashboard
    mostra o aviso até a primeira execução do cron (madrugada seguinte). Isso é
    o comportamento pretendido, não um falso positivo: enquanto não houver uma
    linha, o sistema realmente não tem evidência de que as rotinas rodam — que
    era, literalmente, a situação permanente antes desta migration. Silenciar o
    aviso até a primeira execução faria um cron nunca implantado ficar verde
    para sempre.

    A DEPENDÊNCIA DA 016 É REAL: o trigger de TRUNCATE reusa
    `fn_bloquear_truncate_append_only`, criada lá. `down_revision = "0024"`
    já garante a ordem.
    """
    sql = (_SQL_DIR / "025_registro_de_execucao.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Derruba a tabela e as duas funções próprias dela.

    DESTRUTIVO E IRREVERSÍVEL NO DADO: `drop table` leva junto todo o histórico
    de execução já acumulado, e ele não pode ser reconstruído — o log
    estruturado do Railway tem retenção curta e, passada ela, não existe outra
    testemunha de que uma rotina rodou. Descer daqui devolve o sistema ao
    estado em que ele não sabe o próprio estado.

    `fn_bloquear_truncate_append_only` NÃO é derrubada: ela é da 016 e serve
    outras cinco tabelas. O `drop table` já leva o trigger que a referencia.

    A ordem é tabela e depois funções: enquanto a tabela existir, os triggers
    dependem delas e o `drop function` sem CASCADE seria recusado — o que é a
    recusa certa, e não algo a contornar com CASCADE.
    """
    op.execute("drop table if exists execucao_rotina")
    op.execute("drop function if exists fn_execucao_rotina_append_only()")
    op.execute("drop function if exists fn_execucao_rotina_carimbo()")
