"""024 - `movimento_bancario` ganha proveniência de arquivo: `arquivo_sha256`
(SHA-256 dos bytes do OFX importado) e `conta_origem` (BANKID/ACCTID), com
CHECK exigindo o hash de quem se declara `origem = 'ofx'`.

Baseline convertido de migrations/024_proveniencia_do_extrato.sql.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-16
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Duas colunas nullable e um CHECK. Nenhuma linha existente é reescrita.

    O UPGRADE É SEGURO EM BASE COM DADOS PORQUE AS COLUNAS NASCEM NULAS e todo
    movimento gravado até aqui tem `origem = 'manual'` — o único caminho de
    produção que já existiu (`POST /cobranca/movimentos`) grava a palavra fixa.
    O segundo ramo do CHECK (`origem <> 'ofx' and ... is null`) é portanto
    verdadeiro para a tabela inteira, e `ADD CONSTRAINT` valida sem tocar em
    nada.

    A EXCEÇÃO A CONFERIR ANTES, porque falha com 23514 e aborta o upgrade:

        select count(*) from movimento_bancario where origem = 'ofx';

    Retornando diferente de zero, alguém gravou o carimbo 'ofx' por SQL direto,
    sem arquivo por trás — que é exatamente a auto-declaração que esta migration
    existe para tornar impossível. O tratamento é reconciliar essas linhas
    contra o extrato real antes de subir, não afrouxar a constraint.

    NÃO HÁ BACK-FILL, e não é omissão: `movimento_bancario` é imutável desde a
    009 (OC012 recusa UPDATE de linha), então nem haveria como preencher a
    proveniência de um movimento antigo. É o comportamento pretendido — um
    lançamento digitado no passado não deve poder virar "importado" depois.
    """
    sql = (_SQL_DIR / "024_proveniencia_do_extrato.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Derruba o CHECK, o índice e as duas colunas.

    DESTRUTIVO E IRREVERSÍVEL NO DADO: `drop column` leva junto o hash de todo
    extrato já importado. Como a tabela é imutável (OC012), essa proveniência
    não pode ser regravada depois — reimportar os mesmos arquivos não a
    reconstrói, porque o `documento` (FITID) já existe e o import é idempotente:
    ele PULA as linhas, corretamente, e nada é recriado. Descer daqui, numa base
    que já importou extrato, apaga a prova documental de forma definitiva.

    O CHECK cai ANTES das colunas por clareza de intenção, não por necessidade
    (`drop column` já o levaria em cascata): quem lê o downgrade tem que ver
    que a garantia é removida explicitamente.

    Os movimentos com `origem = 'ofx'` PERMANECEM com esse valor — ele continua
    válido pelo CHECK `movimento_origem_valida` da 009, que admite
    ('manual','ofx'). Ficam sendo o que eram antes desta migration: um carimbo
    sem nada atrás.
    """
    op.execute("""
        alter table movimento_bancario
            drop constraint if exists movimento_proveniencia_coerente
    """)
    op.execute("drop index if exists idx_movimento_arquivo")
    op.execute("""
        alter table movimento_bancario
            drop column if exists conta_origem,
            drop column if exists arquivo_sha256
    """)
