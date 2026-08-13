"""017 - gate de liquidação: quitação exige lastro em todas as parcelas e
write-off (baixada_prejuizo) encerra a cobrança sem devolver capital ao teto.

Baseline convertido de migrations/017_gate_de_liquidacao.sql.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-12
"""

from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

# Reexecutadas no downgrade, em ORDEM CRESCENTE, para restaurar os corpos
# anteriores das três funções redefinidas e da view recriada pela 017.
# Ver a explicação da ordem no docstring de downgrade().
_SQL_PARA_RESTAURAR = (
    "006_novacao_e_inadimplencia.sql",  # fn_check_reducao_capital
    "010_compliance_interno.sql",  # v_tomadores_sem_identificacao
    "014_gate_identificacao.sql",  # fn_check_teto_capital
    "015_bordas_do_capital.sql",  # fn_bloquear_alteracao_operacao_comprometida
)


def upgrade() -> None:
    sql = (_SQL_DIR / "017_gate_de_liquidacao.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Reabre o furo da liquidação incondicional.

    PRÉ-CONDIÇÃO: nenhuma operação em 'baixada_prejuizo'. Enquanto o CHECK de
    domínio existir, nenhuma linha pode deixar esse status — mas depois que
    ele cair, qualquer linha que ainda esteja nele vira um valor órfão:
    aceito por um schema que não conhece mais o estado e ignorado por todos
    os `sum(...)` de comprometido restaurados abaixo. O efeito seria capital
    devolvido ao teto em silêncio, sem transição, sem evento e sem erro — o
    oposto do que esta migration decidiu.

    Por isso o downgrade RECUSA descer nesse caso. Não há resposta automática
    correta: transformá-las em 'liquidada' mentiria (devolveria o capital de
    empréstimos perdoados), voltá-las para 'inadimplente' ressuscitaria uma
    cobrança encerrada. É decisão de gestão, tomada antes de descer, e o erro
    aqui é o que obriga a tomá-la em vez de descobrir o estrago depois.

    Três funções foram REDEFINIDAS (fn_check_teto_capital da 014,
    fn_check_reducao_capital da 006 e fn_bloquear_alteracao_operacao_
    comprometida da 015) e uma view recriada (v_tomadores_sem_identificacao
    da 010). PL/pgSQL não tem substituição parcial: descer exige reexecutar o
    SQL dessas migrations para trazer os corpos anteriores de volta. As
    quatro são idempotentes nas partes relevantes (`create or replace`,
    `drop trigger if exists` antes de cada `create trigger`, `create ... if
    not exists`), então reaplicá-las sobre o banco atual não duplica nada.

    A ORDEM É CRESCENTE, e tem que ser: a 006 contém uma versão de
    fn_check_teto_capital ANTERIOR aos gates de registro (013) e de
    identificação (014). Reexecutá-la por último apagaria os dois gates junto
    com o desta migration. Rodando 006 -> 010 -> 014 -> 015, cada corpo acaba
    escrito por quem o definiu por último antes da 017.

    Descer daqui devolve o banco ao estado em que `POST /operacoes/{id}/
    liquidar` libera 100% do capital de uma operação com todas as parcelas em
    aberto. É reversibilidade, não é segurança equivalente.
    """
    pendentes = (
        op.get_bind()
        .execute(sa.text("select count(*) from operacao_credito where status = 'baixada_prejuizo'"))
        .scalar_one()
    )
    if pendentes:
        raise RuntimeError(
            f"{pendentes} operação(ões) em 'baixada_prejuizo': descer esta migration as "
            "deixaria em um status que o schema restaurado não conhece e que nenhum "
            "cálculo de comprometido enxerga — o capital perdido voltaria ao teto em "
            "silêncio. Decida o destino de cada uma (é decisão de gestão, não de "
            "migração) antes de descer."
        )

    op.execute(
        "alter table operacao_credito drop constraint if exists operacao_credito_status_valido"
    )

    for arquivo in _SQL_PARA_RESTAURAR:
        op.execute((_SQL_DIR / arquivo).read_text(encoding="utf-8"))
