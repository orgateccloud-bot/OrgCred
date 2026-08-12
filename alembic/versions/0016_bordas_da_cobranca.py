"""016 - fecha as bordas da cobrança e do compliance (domínio da parcela,
lastro/autoria da baixa e TRUNCATE nas trilhas append-only).

Baseline convertido de migrations/016_bordas_da_cobranca.sql.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "016_bordas_da_cobranca.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Reabre as bordas da cobrança.

    Duas funções foram REDEFINIDAS aqui (fn_parcela_imutavel e
    fn_baixar_parcela, ambas da 009), e PL/pgSQL não tem substituição
    parcial: descer exige reexecutar o SQL da 009 inteiro para trazer as
    versões anteriores de volta. A 009 é idempotente (`create table if not
    exists`, `add column if not exists`, `create unique index if not
    exists`, `create or replace`, `drop trigger if exists` antes de cada
    `create trigger`), então reaplicá-la sobre o banco atual não recria nem
    duplica nada — só volta os dois corpos.

    ORDEM IMPORTA: as constraints saem ANTES da coluna `baixado_por`, e a
    reexecução da 009 vem depois de tudo. Derrubar `parcela_status_valido`
    e recriá-la com o domínio de três valores antes de restaurar
    fn_parcela_imutavel deixaria uma janela em que 'baixada' é aceito pelo
    CHECK e recusado pelo trigger — estado inconsistente, ainda que dentro
    de uma transação de migração.

    Descer daqui devolve o banco ao estado em que `update parcela set status
    = 'baixada'` tira a parcela do atraso E da receita tributável sem
    lastro, movimento_id pode ser repontado, TRUNCATE apaga qualquer uma das
    cinco trilhas (ledger, evento de operação, documento, ocorrência e
    capital social) e a baixa volta a não ter autor. É reversibilidade, não é
    segurança equivalente.
    """
    op.execute("drop trigger if exists trg_bloquear_truncate_ledger on capital_ledger")
    op.execute("drop trigger if exists trg_bloquear_truncate_evento on operacao_evento")
    op.execute("drop trigger if exists trg_bloquear_truncate_documento on tomador_documento")
    op.execute("drop trigger if exists trg_bloquear_truncate_ocorrencia on ocorrencia_atipicidade")
    op.execute(
        "drop trigger if exists trg_bloquear_truncate_capital_social on esc_capital_social"
    )
    op.execute("drop function if exists fn_bloquear_truncate_append_only()")

    op.execute("alter table parcela drop constraint if exists parcela_lastro_obrigatorio")
    op.execute("alter table parcela drop constraint if exists parcela_status_valido")
    op.execute(
        "alter table parcela add constraint parcela_status_valido "
        "check (status in ('aberta','paga','baixada'))"
    )

    # A autoria some junto: mantê-la com fn_baixar_parcela de volta à versão
    # da 009 (que não a preenche) daria uma coluna que existe, aparece na API
    # e nunca mais é escrita — pior do que não existir.
    op.execute("alter table parcela drop column if exists baixado_por")

    sql = (_SQL_DIR / "009_baixa_de_recebimento.sql").read_text(encoding="utf-8")
    op.execute(sql)
