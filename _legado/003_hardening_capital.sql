-- OrgCred — hardening do motor de capital
-- Esta migration corrige TRÊS falhas graves comprovadas por teste de ataque
-- em 2026-07-11 (ver tests/ e REVISAO_2026-07-11.md):
--
--   F1. Race condition: duas ativações concorrentes podiam ambas passar
--       pelo teto (comprovado: 60.000 ativados com capital de 50.000).
--   F2. Redução de capital social não era vigiada: era possível reduzir
--       o capital para baixo do total já comprometido.
--   F3. Máquina de estados não era enforced no banco: proposta -> ativa
--       direto, sem registro na entidade registradora (contrato inválido
--       comprometendo capital).
--
-- Também introduz ERRCODEs próprios (classe 'OC') para a API identificar
-- erros por código SQLSTATE em vez de matching frágil por substring.
--   OC001 = teto de capital excedido
--   OC002 = tomador fora da área de atuação
--   OC003 = transição de status inválida
--   OC004 = ativação sem registro na entidade registradora
--   OC005 = redução de capital abaixo do comprometido

-- ---------------------------------------------------------------------
-- F1 + F3: trigger de operação reescrito
-- ---------------------------------------------------------------------
create or replace function fn_check_teto_capital()
returns trigger as $$
declare
    v_capital_atual         numeric(14,2);
    v_comprometido_outras   numeric(14,2);
    v_disponivel            numeric(14,2);
    v_municipio_ok          boolean;
begin
    -- F3: máquina de estados enforced no banco.
    -- Transições permitidas (qualquer outra é rejeitada):
    --   proposta     -> registrada | cancelada
    --   registrada   -> ativa | cancelada
    --   ativa        -> liquidada | inadimplente | renegociada
    --   inadimplente -> ativa | renegociada | liquidada
    --   renegociada  -> (terminal nesta versão; nova operação é criada)
    --   liquidada    -> (terminal)
    --   cancelada    -> (terminal)
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

    -- INSERT já em estado avançado também é violação da máquina de estados
    if tg_op = 'INSERT' and new.status not in ('proposta','registrada') then
        raise exception
            'Operação não pode ser criada já no status % (operação %).',
            new.status, new.id
            using errcode = 'OC003';
    end if;

    if new.status = 'ativa' and (tg_op = 'INSERT' or old.status is distinct from 'ativa') then

        -- F1: serializa TODAS as ativações. Advisory lock transacional:
        -- a segunda transação concorrente espera a primeira commitar/rollbackar
        -- e então recalcula o disponível já enxergando o resultado dela.
        -- Single-tenant (uma ESC) => lock global é aceitável; ativação de
        -- operação não é caminho de alto throughput neste negócio.
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        -- F3: ativação exige confirmação da entidade registradora (Art. 5º §3º)
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
        -- também sob o mesmo lock, para o ledger não intercalar com ativações
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

-- ---------------------------------------------------------------------
-- F2: vigiar reduções de capital social
-- ---------------------------------------------------------------------
create or replace function fn_check_reducao_capital()
returns trigger as $$
declare
    v_capital_pos_reducao   numeric(14,2);
    v_comprometido          numeric(14,2);
begin
    if new.tipo_evento = 'reducao' then
        -- mesmo lock das ativações: uma redução não pode correr em paralelo
        -- com uma ativação que ainda não commitou
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

create trigger trg_check_reducao_capital
    before insert on esc_capital_social
    for each row execute function fn_check_reducao_capital();
