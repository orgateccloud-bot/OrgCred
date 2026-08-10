-- OrgCred — agenda de parcelas gerada na ativação, imutável depois
--
-- Mesma disciplina do capital_ledger: quem calcula é o BANCO, e o que foi
-- emitido não muda. A agenda é o documento que diz quanto o tomador deve e
-- quando — se ela puder ser reescrita depois, nenhuma cobrança é defensável.
--
-- Gerada dentro da MESMA transação da ativação (o trigger chama
-- fn_gerar_parcelas), então não existe operação ativa sem agenda.
--
-- PREMISSA DE NEGÓCIO (registrada explicitamente, não escondida no código):
-- o primeiro vencimento cai 1 mês após a ativação, e os demais a cada mês.
-- Se a ESC adotar outra regra (dia fixo do mês, carência), muda aqui — e
-- as agendas já emitidas continuam válidas como estão, por serem imutáveis.
--
-- Novo SQLSTATE: OC009 = tentativa de alterar/apagar parcela já emitida.

create table if not exists parcela (
    id                  uuid primary key default uuid_generate_v4(),
    operacao_id         uuid not null references operacao_credito(id),
    numero              int  not null,
    vencimento          date not null,
    valor_amortizacao   numeric(14,2) not null,
    valor_juros         numeric(14,2) not null,
    valor_total         numeric(14,2) not null,
    saldo_devedor_pos   numeric(14,2) not null,
    status              text not null default 'aberta',  -- aberta | paga | baixada
    pago_em             timestamp,
    created_at          timestamp not null default now(),
    constraint parcela_numero_positivo check (numero > 0),
    constraint parcela_valores_nao_negativos check (
        valor_amortizacao >= 0 and valor_juros >= 0 and valor_total >= 0
    ),
    constraint parcela_status_valido check (status in ('aberta','paga','baixada')),
    constraint parcela_unica_por_operacao unique (operacao_id, numero)
);

create index if not exists idx_parcela_operacao on parcela(operacao_id);
create index if not exists idx_parcela_vencimento on parcela(vencimento) where status = 'aberta';

-- ---------------------------------------------------------------------
-- Imutabilidade: valores e datas não mudam depois de emitidos
-- ---------------------------------------------------------------------
-- Só `status` e `pago_em` podem mudar (baixa de recebimento). Qualquer
-- alteração de valor, vencimento ou número é recusada — reescrever a
-- agenda depois de emitida destruiria a base da cobrança.
create or replace function fn_parcela_imutavel()
returns trigger as $$
begin
    if tg_op = 'DELETE' then
        raise exception
            'Parcela % da operação % não pode ser apagada: a agenda é imutável.',
            old.numero, old.operacao_id
            using errcode = 'OC009';
    end if;

    if new.operacao_id is distinct from old.operacao_id
       or new.numero is distinct from old.numero
       or new.vencimento is distinct from old.vencimento
       or new.valor_amortizacao is distinct from old.valor_amortizacao
       or new.valor_juros is distinct from old.valor_juros
       or new.valor_total is distinct from old.valor_total
       or new.saldo_devedor_pos is distinct from old.saldo_devedor_pos then
        raise exception
            'Parcela % da operação % é imutável: só status e pago_em podem mudar.',
            old.numero, old.operacao_id
            using errcode = 'OC009';
    end if;

    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_parcela_imutavel on parcela;
create trigger trg_parcela_imutavel
    before update or delete on parcela
    for each row execute function fn_parcela_imutavel();

-- ---------------------------------------------------------------------
-- Geração da agenda: PRICE e SAC
-- ---------------------------------------------------------------------
-- PRICE: prestação constante. PMT = PV * i / (1 - (1+i)^-n)
-- SAC:   amortização constante. A = PV / n; juros sobre o saldo devedor.
--
-- Taxa ZERO é tratada explicitamente: a fórmula PRICE divide por zero
-- quando i = 0 (o denominador vira 1 - 1 = 0). Sem esse desvio, uma
-- operação sem juros — perfeitamente válida — quebraria a ativação.
--
-- O RESÍDUO DE ARREDONDAMENTO vai todo na última parcela, de modo que
-- sum(valor_amortizacao) = valor_principal EXATAMENTE e o saldo devedor
-- final é 0,00. Sem isso, centavos sobram ou faltam e a quitação nunca
-- fecha — num sistema de crédito isso não é detalhe estético.
create or replace function fn_gerar_parcelas(p_operacao_id uuid)
returns int as $$
declare
    v_op            operacao_credito%rowtype;
    v_taxa          numeric(20,10);
    v_pmt           numeric(20,10);
    v_saldo         numeric(14,2);
    v_juros         numeric(14,2);
    v_amort         numeric(14,2);
    v_total         numeric(14,2);
    v_base          date;
    i               int;
begin
    select * into v_op from operacao_credito where id = p_operacao_id;
    if not found then
        raise exception 'Operação % não existe.', p_operacao_id using errcode = 'OC003';
    end if;

    -- Idempotente: reativar uma inadimplente não regenera a agenda.
    if exists (select 1 from parcela where operacao_id = p_operacao_id) then
        return 0;
    end if;

    v_taxa  := v_op.taxa_juros_mensal / 100.0;
    v_saldo := v_op.valor_principal;
    v_base  := current_date;

    if v_taxa = 0 then
        v_pmt := v_op.valor_principal / v_op.numero_parcelas;
    else
        v_pmt := v_op.valor_principal * v_taxa
                 / (1 - power(1 + v_taxa, -v_op.numero_parcelas));
    end if;

    for i in 1..v_op.numero_parcelas loop
        v_juros := round(v_saldo * v_taxa, 2);

        if v_op.sistema_amortizacao = 'SAC' then
            v_amort := round(v_op.valor_principal / v_op.numero_parcelas, 2);
        else  -- PRICE
            v_amort := round(v_pmt, 2) - v_juros;
        end if;

        -- Última parcela absorve o resíduo: zera o saldo devedor na régua.
        if i = v_op.numero_parcelas then
            v_amort := v_saldo;
        end if;

        v_total := v_amort + v_juros;
        v_saldo := v_saldo - v_amort;

        insert into parcela (
            operacao_id, numero, vencimento,
            valor_amortizacao, valor_juros, valor_total, saldo_devedor_pos
        ) values (
            p_operacao_id, i, (v_base + (i || ' month')::interval)::date,
            v_amort, v_juros, v_total, v_saldo
        );
    end loop;

    return v_op.numero_parcelas;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- Ligação com a ativação
-- ---------------------------------------------------------------------
-- AFTER UPDATE/INSERT: a agenda referencia operacao_credito(id) por FK e
-- precisa da linha já gravada. O trigger de teto (fn_check_teto_capital) é
-- BEFORE porque precisa vetar antes de escrever; este é AFTER porque só
-- age depois que a ativação foi aceita.
create or replace function fn_gerar_parcelas_na_ativacao()
returns trigger as $$
begin
    if new.status = 'ativa'
       and (tg_op = 'INSERT' or old.status is distinct from 'ativa') then
        perform fn_gerar_parcelas(new.id);
    end if;
    return null;
end;
$$ language plpgsql;

drop trigger if exists trg_gerar_parcelas on operacao_credito;
create trigger trg_gerar_parcelas
    after insert or update on operacao_credito
    for each row execute function fn_gerar_parcelas_na_ativacao();
