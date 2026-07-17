"""006 - capital comprometido coerente (inclui inadimplente) + eventos de
ledger para renegociação. Fecha os furos G1/G2 e prepara a novação atômica
— ver migrations/006_capital_comprometido_renegociacao.sql.

Baseline convertido de migrations/006_capital_comprometido_renegociacao.sql
— ver 0001 para a justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-17
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "006_capital_comprometido_renegociacao.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    # Restaura o corpo de fn_check_teto_capital da 0004 re-executando o SQL
    # raw daquela migration (contém apenas o CREATE OR REPLACE da função).
    sql_004 = (_SQL_DIR / "004_auditoria_autor.sql").read_text(encoding="utf-8")
    op.execute(sql_004)

    # Restaura fn_check_reducao_capital ao corpo da 003 (sem
    # fn_capital_comprometido). Não re-executa 003 inteira: o CREATE
    # TRIGGER (sem OR REPLACE) ali falharia porque o trigger já existe.
    op.execute("""
        create or replace function fn_check_reducao_capital()
        returns trigger as $$
        declare
            v_capital_pos_reducao   numeric(14,2);
            v_comprometido          numeric(14,2);
        begin
            if new.tipo_evento = 'reducao' then
                perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

                select capital_atual - new.valor into v_capital_pos_reducao from v_capital_atual;

                select coalesce(sum(valor_principal), 0) into v_comprometido
                from operacao_credito where status = 'ativa';

                if v_capital_pos_reducao < v_comprometido then
                    raise exception
                        'Redução de capital bloqueada: capital resultante (%) ficaria abaixo do total de operações ativas (%). Art. 5º, LC 167/2019.',
                        v_capital_pos_reducao, v_comprometido
                        using errcode = 'OC005';
                end if;
            end if;
            return new;
        end;
        $$ language plpgsql;
    """)

    # Restaura o hash-chain do ledger à ordenação da 005 (created_at, id) e
    # remove a coluna seq. Não re-executa 005 inteira: os CREATE TRIGGER
    # (sem OR REPLACE) ali falhariam porque os triggers já existem.
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
    op.execute("alter table capital_ledger drop column if exists seq")

    op.execute("drop function if exists fn_capital_comprometido(uuid)")
