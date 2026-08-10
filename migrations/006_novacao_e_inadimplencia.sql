-- OrgCred — correção de dois furos no teto de capital do Art. 5º
--
-- Ambos comprovados contra Postgres real antes desta migration existir:
--
--   ativa -> liquidada     liberou R$ 40.000,00 | eventos no ledger: 1
--   ativa -> inadimplente  liberou R$ 40.000,00 | eventos no ledger: 0  <<<
--   ativa -> renegociada   liberou R$ 40.000,00 | eventos no ledger: 0  <<<
--
-- CAUSA: o comprometido era `sum(valor_principal) where status = 'ativa'`.
-- Sair de 'ativa' por QUALQUER porta removia a operação da conta, mas o
-- trigger só gravava evento no ledger para liquidada/cancelada.
--
-- CONSEQUÊNCIA 1 (teto): marcar inadimplência liberava o capital de um
-- empréstimo que NÃO foi pago — o dinheiro está fora, mas o sistema passava
-- a permitir emprestá-lo de novo. Teto legal furado por construção, sem
-- ninguém agir de má-fé.
--
-- CONSEQUÊNCIA 2 (auditoria): o capital_ledger é a cadeia com hash que a
-- tela de Auditoria usa para reconstruir o saldo. Um movimento sem evento
-- correspondente faz a série temporal mentir — e a cadeia segue "íntegra",
-- porque nada foi adulterado, apenas omitido.
--
-- DECISÕES DE NEGÓCIO (confirmadas com o dono do negócio em 2026-08-06):
--   1. Inadimplente CONTINUA comprometendo capital (leitura conservadora e
--      juridicamente segura: o dinheiro não voltou, então ocupa o teto até
--      ser efetivamente liquidado).
--   2. Renegociação passa a ser NOVAÇÃO ATÔMICA — uma função única sob o
--      mesmo advisory lock baixa a original e cria a substituta.
--
-- Novo SQLSTATE: OC008 = substituta de novação criada fora da função atômica.

-- ---------------------------------------------------------------------
-- 1. Vínculo entre a operação renegociada e a que a substituiu
-- ---------------------------------------------------------------------
alter table operacao_credito
    add column if not exists substitui_operacao_id uuid references operacao_credito(id);

alter table operacao_credito
    drop constraint if exists nao_substitui_a_si_mesma;
alter table operacao_credito
    add constraint nao_substitui_a_si_mesma
    check (substitui_operacao_id is distinct from id);

create index if not exists idx_operacao_substitui on operacao_credito(substitui_operacao_id);

-- ---------------------------------------------------------------------
-- 2. Trigger principal: inadimplente compromete capital; renegociação
--    só pela função de novação
-- ---------------------------------------------------------------------
create or replace function fn_check_teto_capital()
returns trigger as $$
declare
    v_capital_atual         numeric(14,2);
    v_comprometido_outras   numeric(14,2);
    v_disponivel            numeric(14,2);
    v_municipio_ok          boolean;
    v_usuario_id            text;
    v_comprometia_antes     boolean;
    v_compromete_agora      boolean;
begin
    v_usuario_id := nullif(current_setting('app.user_id', true), '');

    -- Fonte única da verdade sobre o que ocupa o teto. 'inadimplente' entra
    -- aqui: o título saiu de 'ativa', mas o dinheiro continua fora.
    v_comprometia_antes := tg_op = 'UPDATE' and old.status in ('ativa','inadimplente');
    v_compromete_agora  := new.status in ('ativa','inadimplente');

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

        -- Renegociar só dentro de fn_novar_operacao, que faz a baixa e a
        -- criação da substituta na MESMA transação e sob o mesmo lock. Fora
        -- dela, a original sairia do comprometido sem substituta amarrada —
        -- e nada impediria criar a substituta depois, contando o capital
        -- duas vezes em janelas diferentes.
        if new.status = 'renegociada'
           and coalesce(current_setting('app.novacao_em_curso', true), '') <> '1' then
            raise exception
                'Renegociação exige novação atômica: use fn_novar_operacao (operação %).',
                new.id
                using errcode = 'OC008';
        end if;
    end if;

    if tg_op = 'INSERT' and new.status not in ('proposta','registrada') then
        raise exception
            'Operação não pode ser criada já no status % (operação %).',
            new.status, new.id
            using errcode = 'OC003';
    end if;

    -- Substituta de novação também só nasce dentro da função atômica.
    if tg_op = 'INSERT' and new.substitui_operacao_id is not null
       and coalesce(current_setting('app.novacao_em_curso', true), '') <> '1' then
        raise exception
            'Operação substituta só pode ser criada por fn_novar_operacao (operação %).',
            new.id
            using errcode = 'OC008';
    end if;

    -- ENTRADA no comprometido: só quando a operação passa a ocupar o teto
    -- vindo de um estado que NÃO ocupava. Antes, reativar uma inadimplente
    -- (inadimplente -> ativa) reexecutava a checagem e gravava um segundo
    -- evento de ativação — com 'inadimplente' já comprometendo, isso seria
    -- contar duas vezes o mesmo dinheiro no ledger.
    if v_compromete_agora and (tg_op = 'INSERT' or not v_comprometia_antes) then
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
        where status in ('ativa','inadimplente') and id <> new.id;

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

    -- SAÍDA do comprometido: qualquer transição que deixa de ocupar o teto
    -- vindo de um estado que ocupava. Cobre liquidada E renegociada, e agora
    -- também a partir de 'inadimplente' (liquidar um inadimplente devolve o
    -- capital, coisa que antes não gerava evento algum).
    --
    -- ativa -> inadimplente NÃO cai aqui de propósito: os dois estados
    -- comprometem, então não há movimento de capital para registrar. Quem
    -- marcou a inadimplência fica na trilha da aplicação, não no ledger de
    -- CAPITAL, que só registra dinheiro entrando ou saindo do teto.
    if tg_op = 'UPDATE' and v_comprometia_antes and not v_compromete_agora then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual into v_capital_atual from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido_outras
        from operacao_credito
        where status in ('ativa','inadimplente') and id <> new.id;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values (
            case when new.status = 'renegociada' then 'renegociacao' else 'liquidacao' end,
            new.valor_principal, new.id,
            v_capital_atual - v_comprometido_outras, v_usuario_id
        );
    end if;

    new.updated_at := now();
    return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- 3. Redução de capital: mesma definição de comprometido
-- ---------------------------------------------------------------------
create or replace function fn_check_reducao_capital()
returns trigger as $$
declare
    v_capital_pos_reducao numeric(14,2);
    v_comprometido        numeric(14,2);
begin
    if new.tipo_evento = 'reducao' then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual - new.valor into v_capital_pos_reducao from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido
        from operacao_credito
        where status in ('ativa','inadimplente');

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

-- ---------------------------------------------------------------------
-- 4. Novação atômica
-- ---------------------------------------------------------------------
-- Baixa a operação original e cria a substituta na MESMA transação, sob o
-- mesmo advisory lock do teto. A substituta nasce em 'registrada' (não
-- 'ativa'): ela ainda não compromete capital, e a ativação segue passando
-- pelos gates normais (teto, município, registro). O que esta função
-- garante é que a original SAIU antes de a substituta poder entrar —
-- impossibilitando a janela em que as duas contariam ao mesmo tempo.
create or replace function fn_novar_operacao(
    p_operacao_id           uuid,
    p_valor_principal       numeric,
    p_taxa_juros_mensal     numeric,
    p_sistema_amortizacao   text,
    p_numero_parcelas       int,
    p_registro_entidade_ref text default null
)
returns uuid as $$
declare
    v_original  operacao_credito%rowtype;
    v_nova_id   uuid;
begin
    perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

    select * into v_original from operacao_credito where id = p_operacao_id for update;
    if not found then
        raise exception 'Operação % não existe.', p_operacao_id using errcode = 'OC003';
    end if;

    if v_original.status not in ('ativa','inadimplente') then
        raise exception
            'Só operação ativa ou inadimplente pode ser renegociada (operação % está em %).',
            p_operacao_id, v_original.status
            using errcode = 'OC003';
    end if;

    -- Libera os gates de renegociação apenas dentro desta transação.
    perform set_config('app.novacao_em_curso', '1', true);

    update operacao_credito set status = 'renegociada' where id = p_operacao_id;

    insert into operacao_credito
        (id, tomador_id, tipo, valor_principal, taxa_juros_mensal,
         sistema_amortizacao, numero_parcelas, status, registro_entidade_ref,
         substitui_operacao_id)
    values
        (gen_random_uuid(), v_original.tomador_id, v_original.tipo, p_valor_principal,
         p_taxa_juros_mensal, p_sistema_amortizacao, p_numero_parcelas, 'registrada',
         p_registro_entidade_ref, p_operacao_id)
    returning id into v_nova_id;

    perform set_config('app.novacao_em_curso', '0', true);

    return v_nova_id;
end;
$$ language plpgsql;
