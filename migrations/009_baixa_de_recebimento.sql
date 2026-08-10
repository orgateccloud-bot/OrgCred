-- OrgCred — baixa de recebimento amarrada a movimentação bancária
--
-- PRINCÍPIO: uma parcela só é dada como paga quando existe uma linha de
-- extrato bancário correspondente. Marcar "paga" no sistema sem lastro é
-- o que transforma uma carteira inadimplente em uma carteira aparentemente
-- saudável — e é justamente o que o aging (migration 008) usa para decidir
-- quem entra em inadimplência. Sem esta amarra, bastava um UPDATE para
-- fazer a régua parar de ver o atraso.
--
-- Novos SQLSTATEs:
--   OC011 = baixa inválida (sem movimento, movimento já usado, valor menor)
--   OC012 = movimento bancário é imutável
--
-- ESTORNO É DELIBERADAMENTE AUSENTE. Reverter uma baixa exigiria uma
-- trilha própria (quem estornou, por quê, contra qual movimento) e a
-- decisão de negócio sobre o que acontece com o movimento liberado. Até que
-- essa regra exista, 'paga' é terminal: é preferível não ter o caminho a
-- ter um caminho que apaga o lastro em silêncio. Uma baixa errada se
-- corrige no extrato, com o lançamento de correção do próprio banco.

-- ---------------------------------------------------------------------
-- Movimentação bancária
-- ---------------------------------------------------------------------
-- `documento` é o identificador da linha no extrato (FITID no OFX). O
-- UNIQUE nele é o que torna a importação IDEMPOTENTE: reimportar o mesmo
-- extrato — coisa que acontece o tempo todo na operação real — não duplica
-- crédito nem permite dar duas parcelas por baixadas com o mesmo dinheiro.
create table if not exists movimento_bancario (
    id             uuid primary key default uuid_generate_v4(),
    data_movimento date not null,
    valor          numeric(14,2) not null,
    descricao      text,
    documento      text not null,
    origem         text not null default 'manual',
    usuario_id     text,
    created_at     timestamp not null default clock_timestamp(),
    constraint movimento_valor_positivo check (valor > 0),
    constraint movimento_origem_valida check (origem in ('manual', 'ofx')),
    constraint movimento_documento_unico unique (documento)
);

create index if not exists idx_movimento_data on movimento_bancario(data_movimento desc);

-- Extrato é fato de fora: o sistema registra, não edita. Se a linha
-- estiver errada, quem corrige é o banco, com outro lançamento.
create or replace function fn_movimento_imutavel()
returns trigger as $$
begin
    raise exception 'movimento_bancario é imutável: % não é permitido.', tg_op
        using errcode = 'OC012';
end;
$$ language plpgsql;

drop trigger if exists trg_movimento_imutavel on movimento_bancario;
create trigger trg_movimento_imutavel
    before update or delete on movimento_bancario
    for each row execute function fn_movimento_imutavel();

-- ---------------------------------------------------------------------
-- Amarra parcela <-> movimento
-- ---------------------------------------------------------------------
alter table parcela
    add column if not exists movimento_id uuid references movimento_bancario(id);

-- UNIQUE: um movimento paga NO MÁXIMO uma parcela. Sem isto, o mesmo
-- crédito de R$ 1.000 no extrato poderia baixar dez parcelas.
create unique index if not exists idx_parcela_movimento_unico
    on parcela(movimento_id) where movimento_id is not null;

-- ---------------------------------------------------------------------
-- Guard: 'paga' só existe com lastro
-- ---------------------------------------------------------------------
-- Substitui fn_parcela_imutavel (migration 007), somando as regras da
-- baixa às de imutabilidade que já existiam.
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
            'Parcela % da operação % é imutável: só a baixa pode alterá-la.',
            old.numero, old.operacao_id
            using errcode = 'OC009';
    end if;

    -- Baixa é terminal (ver nota sobre estorno no topo do arquivo).
    if old.status = 'paga' and new.status is distinct from 'paga' then
        raise exception
            'Parcela % já baixada não pode voltar a aberta: não há estorno definido.',
            old.numero
            using errcode = 'OC011';
    end if;

    -- O coração desta migration: não existe "paga" sem linha de extrato.
    if new.status = 'paga' and new.movimento_id is null then
        raise exception
            'Parcela % não pode ser dada como paga sem movimento bancário correspondente.',
            new.numero
            using errcode = 'OC011';
    end if;

    return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- Único caminho para baixar
-- ---------------------------------------------------------------------
-- As validações vivem aqui (e não na aplicação) pelo mesmo motivo do resto
-- do motor: a aplicação não é a única porta do banco, e um script de
-- correção rodando SQL direto tem que esbarrar nas mesmas regras.
--
-- O valor do movimento precisa cobrir a parcela (>=), não ser igual: juros
-- de mora fazem o tomador pagar MAIS que o valor original, e recusar isso
-- impediria a baixa de todo pagamento atrasado — justamente os que mais
-- importam para a régua de cobrança.
create or replace function fn_baixar_parcela(
    p_parcela_id   uuid,
    p_movimento_id uuid
) returns void as $$
declare
    v_parcela   parcela%rowtype;
    v_movimento movimento_bancario%rowtype;
begin
    select * into v_parcela from parcela where id = p_parcela_id for update;
    if not found then
        raise exception 'Parcela % não existe.', p_parcela_id using errcode = 'OC011';
    end if;
    if v_parcela.status <> 'aberta' then
        raise exception 'Parcela % não está em aberto (situação: %).',
            v_parcela.numero, v_parcela.status using errcode = 'OC011';
    end if;

    select * into v_movimento from movimento_bancario where id = p_movimento_id;
    if not found then
        raise exception 'Movimento bancário % não existe.', p_movimento_id
            using errcode = 'OC011';
    end if;

    if exists (select 1 from parcela where movimento_id = p_movimento_id) then
        raise exception
            'Movimento bancário % já foi usado para baixar outra parcela.', p_movimento_id
            using errcode = 'OC011';
    end if;

    if v_movimento.valor < v_parcela.valor_total then
        raise exception
            'Movimento de % não cobre a parcela % (valor devido: %).',
            v_movimento.valor, v_parcela.numero, v_parcela.valor_total
            using errcode = 'OC011';
    end if;

    update parcela
       set status = 'paga',
           pago_em = clock_timestamp(),
           movimento_id = p_movimento_id
     where id = p_parcela_id;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- Leitura: movimentos ainda não conciliados
-- ---------------------------------------------------------------------
create or replace view v_movimentos_disponiveis as
select m.*
from movimento_bancario m
where not exists (select 1 from parcela p where p.movimento_id = m.id);
