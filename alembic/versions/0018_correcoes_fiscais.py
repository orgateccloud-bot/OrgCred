"""018 - correções de conteúdo tributário na apuração fiscal: parâmetro do
período apurado, competência sem a agenda renegociada, caixa ancorado no
extrato e mora/multa recebidas dentro da base.

Baseline convertido de migrations/018_correcoes_fiscais.sql.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "018_correcoes_fiscais.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Devolve a apuração ao cálculo da 011 — com os quatro erros de conteúdo.

    A ORDEM IMPORTA, e a armadilha aqui é `CREATE OR REPLACE VIEW`: ele NÃO
    remove colunas de uma view existente, e mesmo se removesse não adiantaria,
    porque `select *` é expandido contra a tabela COMO ELA ESTÁ NO MOMENTO da
    execução — reaplicar o SQL da 011 com as colunas novas ainda na tabela
    apenas reescreve a view incluindo `receita_demais` e `receita_total` de
    novo. O drop das colunas então falha com DependentObjectsStillExist
    (reproduzido em 2026-08-12 contra Postgres 16), e com CASCADE levaria a
    view junto, deixando o schema sem ela.

    Daí a sequência: DERRUBAR a view, derrubar as colunas, e só então
    reexecutar o SQL da 011 — que recria a view com a lista de colunas de
    então e, de quebra, restaura o corpo antigo de fn_apurar_trimestre, o
    outro objeto que esta migration substituiu. A 011 é idempotente nas
    partes relevantes (`create table if not exists`, `create or replace
    view/function`, `drop trigger if exists` antes do `create trigger`), então
    reaplicá-la sobre o banco atual não duplica nada.

    PERDA DE DADO ASSUMIDA: `receita_demais` é a única linha do sistema que
    guarda quanta mora e multa foram recebidas em cada trimestre, e descer
    apaga essa coluna. `receita_total` é gerada e se reconstrói sozinha, mas a
    mora não — ela seria recalculável apenas enquanto os movimentos bancários
    e as parcelas correspondentes continuarem no banco. Não há como preservá-la
    num schema que não tem onde guardá-la, e inventar uma tabela de arquivo
    aqui seria criar, no downgrade, estrutura que a subida nunca criou.

    O QUE FICA DE PÉ depois de descer: as apurações já gravadas continuam lá,
    imutáveis, com os números CERTOS calculados por esta migration — o
    downgrade não as reescreve (nem poderia: OC016). Elas passam a conviver
    com apurações novas calculadas pela regra errada, e a diferença entre
    versões do mesmo trimestre deixa de ter explicação no schema. É
    reversibilidade, não é equivalência: descer daqui volta a aplicar a
    alíquota de hoje a períodos passados, a somar as duas agendas de uma
    novação, a ancorar o caixa na data da conciliação e a descartar a mora.
    """
    op.execute("drop view if exists v_apuracao_vigente")
    op.execute("alter table apuracao_fiscal drop column if exists receita_total")
    op.execute("alter table apuracao_fiscal drop column if exists receita_demais")

    op.execute((_SQL_DIR / "011_apuracao_fiscal.sql").read_text(encoding="utf-8"))
