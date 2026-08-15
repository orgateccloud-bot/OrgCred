"""020 - a hash-chain do capital_ledger deixa de ser ordenada por `created_at`
(o instante de ABERTURA da transação) e passa a ser ancorada em `seq`, uma
chave monotônica atribuída na gravação.

Baseline convertido de migrations/020_hashchain_monotonica.sql.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-15
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "020_hashchain_monotonica.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Devolve a cadeia ao estado da 005: encadeada e verificada por `created_at`.

    O QUE VOLTA JUNTO É O DEFEITO, e essa é a única coisa que precisa ser
    lida antes de rodar isto. A 005 encadeia no `current_hash` da última
    linha por `(created_at desc, id desc)` e verifica com
    `lag(...) over (created_at, id)`; como `created_at` tem default `now()`
    — que é o `transaction_timestamp()`, fixado quando a transação ABRE —,
    duas transações sobrepostas produzem uma linha que encadeia certo e
    carimba um horário anterior ao de quem gravou antes dela. A verificação
    reordena, inverte as duas e acusa AMBAS de adulteração. Descer daqui
    reabre exatamente isso: `GET /auditoria` volta a poder reportar
    adulteração inexistente, e uma adulteração real volta a ser
    indistinguível de uma corrida benigna.

    NENHUM HASH É RECALCULADO NA DESCIDA, e nenhum precisa ser: `seq` nunca
    entrou no digest. Os `current_hash`/`prev_hash` gravados sob a 020 são
    bit a bit os mesmos que a fórmula da 005 recalcula — o que muda é só a
    ORDEM em que a verificação os percorre. Para as linhas gravadas em
    transações que não se sobrepuseram (a esmagadora maioria), as duas
    ordens coincidem e a cadeia continua se declarando íntegra depois do
    downgrade. Para as que se sobrepuseram, o falso positivo reaparece.

    A ORDEM DAS OPERAÇÕES importa: as duas funções são restauradas ANTES de
    a coluna sumir. Fazer o contrário deixaria, entre um comando e outro,
    um `fn_calcular_hash_ledger` referenciando uma coluna inexistente — e
    qualquer INSERT no ledger nessa janela falharia com erro de coluna, o
    que numa migration transacional significa abortar a descida no meio.

    A AUTORIA DE `created_at` TAMBÉM VOLTA PARA QUEM ESCREVE, e isso é
    correto aqui, não um esquecimento. A 020 passou a sobrescrever
    `new.created_at := now()` no trigger porque, com a cadeia ancorada em
    `seq`, nada mais amarrava o carimbo à posição da linha — um INSERT
    antedatado passaria na verificação. A função da 005 restaurada abaixo
    não sobrescreve nada, e não precisa: ela volta a percorrer a cadeia por
    `(created_at, id)`, e é justamente essa ordenação que reordena a linha
    antedatada para o passado e acusa a quebra. Ou seja, as duas versões
    fecham o mesmo buraco por caminhos diferentes — e nenhum estado
    intermediário desta descida fica com os dois desligados ao mesmo tempo,
    porque o `create or replace` é atômico dentro da transação da migration.

    `capital_ledger_seq_seq` não é derrubada explicitamente: foi criada com
    `owned by capital_ledger.seq` justamente para ir embora junto com a
    coluna. O `drop sequence if exists` fica como rede para o caso de a
    coluna já ter sido removida à mão antes.
    """
    op.execute("""
        create or replace function fn_calcular_hash_ledger()
        returns trigger as $$
        declare
            v_prev_hash varchar(64);
        begin
            select current_hash into v_prev_hash
            from capital_ledger
            order by created_at desc, id desc
            limit 1;

            new.prev_hash := v_prev_hash;
            new.current_hash := encode(
                digest(
                    coalesce(v_prev_hash, '') || '|' ||
                    new.evento_tipo || '|' ||
                    new.valor::text || '|' ||
                    coalesce(new.operacao_id::text, '') || '|' ||
                    new.saldo_disponivel_pos::text || '|' ||
                    coalesce(new.usuario_id, '') || '|' ||
                    new.created_at::text,
                    'sha256'
                ),
                'hex'
            );
            return new;
        end;
        $$ language plpgsql;
    """)

    op.execute("""
        create or replace function fn_verificar_cadeia_ledger()
        returns table(id uuid, motivo text) as $$
        begin
            return query
            with ordenado as (
                select
                    l.id,
                    l.evento_tipo,
                    l.valor,
                    l.operacao_id,
                    l.saldo_disponivel_pos,
                    l.usuario_id,
                    l.created_at,
                    l.prev_hash,
                    l.current_hash,
                    lag(l.current_hash) over (order by l.created_at, l.id) as hash_anterior_esperado
                from capital_ledger l
            )
            select
                o.id,
                case
                    when o.prev_hash is distinct from o.hash_anterior_esperado
                        then 'prev_hash não corresponde ao current_hash da linha anterior'
                    when o.current_hash is distinct from encode(
                        digest(
                            coalesce(o.prev_hash, '') || '|' ||
                            o.evento_tipo || '|' ||
                            o.valor::text || '|' ||
                            coalesce(o.operacao_id::text, '') || '|' ||
                            o.saldo_disponivel_pos::text || '|' ||
                            coalesce(o.usuario_id, '') || '|' ||
                            o.created_at::text,
                            'sha256'
                        ),
                        'hex'
                    ) then 'current_hash não bate com o recalculado — linha possivelmente adulterada'
                    else null
                end as motivo
            from ordenado o
            where o.prev_hash is distinct from o.hash_anterior_esperado
               or o.current_hash is distinct from encode(
                    digest(
                        coalesce(o.prev_hash, '') || '|' ||
                        o.evento_tipo || '|' ||
                        o.valor::text || '|' ||
                        coalesce(o.operacao_id::text, '') || '|' ||
                        o.saldo_disponivel_pos::text || '|' ||
                        coalesce(o.usuario_id, '') || '|' ||
                        o.created_at::text,
                        'sha256'
                    ),
                    'hex'
                );
        end;
        $$ language plpgsql stable;
    """)

    op.execute(
        "comment on function fn_verificar_cadeia_ledger() is "
        "'Recalcula e valida a cadeia de hash do capital_ledger. "
        "SELECT * FROM fn_verificar_cadeia_ledger() — 0 linhas = íntegro.'"
    )
    op.execute("comment on column capital_ledger.created_at is null")

    op.execute("drop index if exists capital_ledger_seq_unico")
    op.execute("alter table capital_ledger drop column if exists seq")
    op.execute("drop sequence if exists capital_ledger_seq_seq")
