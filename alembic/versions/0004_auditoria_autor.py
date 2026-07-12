"""004 - trilha de auditoria com autor (SET LOCAL app.user_id).

Baseline convertido de migrations/004_auditoria_autor.sql — ver 0001 para a
justificativa de manter o SQL raw como fonte de verdade.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-12
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    sql = (_SQL_DIR / "004_auditoria_autor.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    # Reverte apenas o CORPO de fn_check_teto_capital() para a versão sem
    # usuario_id (pré-0004). Não re-executa 003_hardening_capital.sql
    # inteiro: o CREATE TRIGGER (sem OR REPLACE) ali falharia porque o
    # trigger já existe desde 0003.
    op.execute("""
        create or replace function fn_check_teto_capital()
        returns trigger as $$
        declare
            v_capital_atual         numeric(14,2);
            v_comprometido_outras   numeric(14,2);
            v_disponivel            numeric(14,2);
            v_municipio_ok          boolean;
        begin
            if tg_op = 'UPDATE' and new.status is distinct from old.status then
                if not (
                    (old.status = 'proposta'     and new.status in ('registrada','cancelada')) or
                    (old.status = 'registrada'   and new.status in ('ativa','cancelada')) or
                    (old.status = 'ativa'        and new.status in ('liquidada','inadimplente','renegociada')) or
                    (old.status = 'inadimplente' and new.status in ('ativa','renegociada','liquidada'))
                ) then
                    raise exception
                        'Transição de status inválida: % -> % (operação %).',
                        old.status, new.status, new.id
                        using errcode = 'OC003';
                end if;
            end if;

            if tg_op = 'INSERT' and new.status not in ('proposta','registrada') then
                raise exception
                    'Operação não pode ser criada já no status % (operação %).',
                    new.status, new.id
                    using errcode = 'OC003';
            end if;

            if new.status = 'ativa' and (tg_op = 'INSERT' or old.status is distinct from 'ativa') then
                perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

                if new.registro_entidade_ref is null or length(trim(new.registro_entidade_ref)) = 0 then
                    raise exception
                        'Ativação bloqueada: operação % sem registro na entidade registradora (Art. 5º §3º, LC 167/2019).',
                        new.id
                        using errcode = 'OC004';
                end if;

                select municipio_autorizado into v_municipio_ok
                from tomador where id = new.tomador_id;

                if not v_municipio_ok then
                    raise exception
                        'Tomador fora da área de atuação autorizada (Art. 1º, LC 167/2019). Operação % bloqueada.',
                        new.id
                        using errcode = 'OC002';
                end if;

                select capital_atual into v_capital_atual from v_capital_atual;

                select coalesce(sum(valor_principal), 0) into v_comprometido_outras
                from operacao_credito
                where status = 'ativa' and id <> new.id;

                v_disponivel := v_capital_atual - v_comprometido_outras;

                if new.valor_principal > v_disponivel then
                    raise exception
                        'Teto de capital excedido (Art. 5º, LC 167/2019). Capital disponível: %, valor solicitado: %. Operação % bloqueada.',
                        v_disponivel, new.valor_principal, new.id
                        using errcode = 'OC001';
                end if;

                insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos)
                values ('ativacao_operacao', new.valor_principal, new.id, v_disponivel - new.valor_principal);

            end if;

            if tg_op = 'UPDATE' and new.status in ('liquidada','cancelada') and old.status = 'ativa' then
                perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

                select capital_atual into v_capital_atual from v_capital_atual;

                select coalesce(sum(valor_principal), 0) into v_comprometido_outras
                from operacao_credito
                where status = 'ativa' and id <> new.id;

                insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos)
                values ('liquidacao', new.valor_principal, new.id, v_capital_atual - v_comprometido_outras);
            end if;

            new.updated_at := now();
            return new;
        end;
        $$ language plpgsql;
    """)
