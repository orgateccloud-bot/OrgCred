"""021 - registro em entidade registradora não nasce confirmado: a máquina de
estados de `registro_operacao` passa a guardar também o INSERT (OC018).

Baseline convertido de migrations/021_registro_nasce_pendente.sql.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-15
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """ATENÇÃO PARA APLICAR EM BASE COM DADOS: o trigger só vale para linhas
    NOVAS. Registros que já nasceram confirmados continuam confirmados e
    continuam destravando a ativação pelo gate OC004 — nada aqui os revoga,
    pela mesma razão que a 013 não revogou operações já ativas (revogar
    retroativamente não devolveria o dinheiro emprestado, só quebraria a
    carteira existente). Quem quiser saber se existem, e quantos, a consulta é:

        select r.id, r.operacao_id, r.entidade, r.protocolo, r.enviado_em
          from registro_operacao r
         where r.status = 'confirmado'
           and r.enviado_em = r.confirmado_em;

    A igualdade dos dois carimbos é a assinatura do INSERT direto: o caminho
    legítimo grava `enviado_em` na abertura e `confirmado_em` na confirmação,
    em comandos distintos, e `clock_timestamp()` avança entre eles. Não é
    prova (um INSERT poderia carimbar datas distintas de propósito), é o
    varredor barato para saber se o buraco chegou a ser usado.
    """
    sql = (_SQL_DIR / "021_registro_nasce_pendente.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Reabre o INSERT, reaplicando a definição da 012.

    O QUE VOLTA JUNTO É O DEFEITO: `fn_registro_transicao` volta a ser
    `before update or delete`, e `insert into registro_operacao (..., status,
    protocolo, confirmado_em) values (..., 'confirmado', 'qualquer-coisa',
    now())` volta a passar. Como o gate OC004 da 013 continua no ar e continua
    exigindo apenas que exista UMA linha confirmada, descer daqui devolve ao
    Art. 5º §3º a força que ele tinha quando `registro_entidade_ref` era texto
    livre — a diferença é só o nome da coluna em que se digita.

    A 012 é idempotente para este fim, como a 006 é para a 0013: além do
    `create or replace` na função e do `drop trigger if exists` + `create
    trigger` (que é o que efetivamente reverte a forma do trigger), só faz
    `create table if not exists`, `create index if not exists` e `create or
    replace view`. Nenhuma linha de dado é tocada, e as duas CHECK constraints
    da própria 012 seguem valendo — o que se perde são as três guardas desta
    migration (nascimento em pendente; pendente sem protocolo/confirmado_em/
    motivo_rejeicao, também em UPDATE; e confirmação nunca anterior ao envio),
    não as garantias de forma.
    """
    sql_012 = (_SQL_DIR / "012_contrato_e_registro.sql").read_text(encoding="utf-8")
    op.execute(sql_012)
