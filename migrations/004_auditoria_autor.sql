-- OrgCred — trilha de auditoria com autor
--
-- capital_ledger.usuario_id existe desde a migration 002, mas o trigger
-- inseria eventos sem saber quem executou a ação — a autenticação (Fase 2
-- da modernização) e a propagação de user_id (Fase 6) fecham essa lacuna.
--
-- Padrão: a API abre `SET LOCAL app.user_id = '<uuid-do-jwt>'` na mesma
-- transação da ativação/liquidação; o trigger lê via
-- `current_setting('app.user_id', true)` (o segundo argumento `true` evita
-- erro se a variável não estiver setada — trilha continua funcionando,
-- só sem autor, em qualquer caminho que ainda não propague o usuário).
--
-- nullif(..., '') é necessário: uma vez que uma GUC customizada (classe
-- 'app') é setada em uma conexão física, `SET LOCAL app.user_id TO DEFAULT`
-- (ou o fim natural da transação em conexões de pool reutilizadas) resulta
-- em string vazia, não NULL, pelo resto da vida daquela conexão — sem o
-- nullif, ativações sem usuário autenticado gravariam '' em vez de NULL no
-- ledger, dependendo de qual conexão física o pool entregou.

create or replace function fn_check_teto_capital()
returns trigger as $$
declare
    v_capital_atual         numeric(14,2);
    v_comprometido_outras   numeric(14,2);
    v_disponivel            numeric(14,2);
    v_municipio_ok          boolean;
    v_usuario_id            text;
begin
    v_usuario_id := nullif(current_setting('app.user_id', true), '');

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

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values ('ativacao_operacao', new.valor_principal, new.id, v_disponivel - new.valor_principal, v_usuario_id);

    end if;

    if tg_op = 'UPDATE' and new.status in ('liquidada','cancelada') and old.status = 'ativa' then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual into v_capital_atual from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido_outras
        from operacao_credito
        where status = 'ativa' and id <> new.id;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values ('liquidacao', new.valor_principal, new.id, v_capital_atual - v_comprometido_outras, v_usuario_id);
    end if;

    new.updated_at := now();
    return new;
end;
$$ language plpgsql;
