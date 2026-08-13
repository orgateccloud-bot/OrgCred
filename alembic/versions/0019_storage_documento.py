"""019 - a evidência de identificação passa a ter bytes: referência do objeto
no storage em tomador_documento, única e congelada pelo trigger OC013.

Baseline convertido de migrations/019_storage_documento.sql.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "019_storage_documento.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Devolve `tomador_documento` ao estado da 010: hash sem arquivo.

    A ORDEM importa pouco aqui (derrubar a coluna leva junto o índice parcial
    e o CHECK que dependem dela), mas o `drop` explícito de cada objeto está
    escrito para que o downgrade continue correto se algum dia a coluna
    deixar de ser o único suporte deles.

    PERDA DE DADO ASSUMIDA, e é a parte que precisa ser lida antes de rodar:
    `storage_objeto` é a ÚNICA ligação entre a linha do banco e o arquivo
    guardado no bucket. Descer daqui não apaga os objetos — apaga o endereço
    deles. Os bytes continuam no Supabase Storage, sem nada no sistema
    dizendo a que tomador ou a que documento pertencem, e a única
    reconstrução possível seria por convenção de nome de caminho
    ('<bucket>/<tomador_id>/<sha256>'), que o schema deixa de conhecer.

    O que sobrevive intacto: `sha256`, `nome_arquivo`, `arquivado_em` e
    `retencao_ate` de cada evidência, mais o gate OC019 da 014, que continua
    exigindo a EXISTÊNCIA da linha para ativar operação. Ou seja, descer
    devolve exatamente o defeito que a 019 corrigiu — a exigência legal de
    identificação satisfeita por um hash sem arquivo —, e não uma versão
    parcial dele.

    O comentário de `fn_documento_retencao()` não é restaurado ao estado
    anterior porque não havia estado anterior: a 010 não comentava a função.
    Um comentário citando a migration 019 num schema que não a tem é ruído
    inofensivo; apagá-lo com um `comment ... is null` seria escrever um
    downgrade que finge mais reversibilidade do que existe.
    """
    op.execute("drop index if exists tomador_documento_storage_objeto_unico")
    op.execute(
        "alter table tomador_documento "
        "drop constraint if exists tomador_documento_storage_objeto_valido"
    )
    op.execute("alter table tomador_documento drop column if exists storage_objeto")
