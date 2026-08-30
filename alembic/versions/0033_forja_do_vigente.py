"""033 - o vigente não se fabrica por INSERT: as duas tabelas de
versão ganham MONOTONIA DE VERSÃO (mata o salto para 99, que forjava o vigente).
O acoplamento da fórmula a um CHECK foi tentado e revertido — ver o .sql.

Fecha o forge reproduzido: INSERT direto de versão 99 com corpo/valores
arbitrários virava a linha vigente (v_contrato_vigente / v_apuracao_vigente
servem a maior versão), porque a imutabilidade da 016/017/018 só guardava
UPDATE/DELETE. Mesma classe do apêndice de parcela fechado na 027.

Baseline convertido de migrations/033_forja_do_vigente.sql.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-28
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Dois triggers BEFORE INSERT de monotonia de versão — só isso.

    Não há CHECK de aritmética: uma versão anterior desta migration o tinha, e
    um teste o derrubou com razão (ver o cabeçalho do .sql). Os triggers só agem
    sobre INSERTs futuros; não revisitam o que está gravado, então aplica em
    base com dados sem risco.
    """
    sql = (_SQL_DIR / "033_forja_do_vigente.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Remove os dois triggers e o CHECK. Reabre a forja do vigente por INSERT
    direto — nas duas tabelas."""
    op.execute("drop trigger if exists trg_contrato_versao_sequencial on contrato_emprestimo")
    op.execute("drop function if exists fn_contrato_versao_sequencial()")
    op.execute("drop trigger if exists trg_apuracao_versao_sequencial on apuracao_fiscal")
    op.execute("drop function if exists fn_apuracao_versao_sequencial()")
