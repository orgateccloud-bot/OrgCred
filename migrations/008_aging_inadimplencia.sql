-- OrgCred — aging de inadimplência, transição automática e trilha de autoria
--
-- PROBLEMA QUE ESTA MIGRATION RESOLVE
--
-- Até aqui, `ativa -> inadimplente` não deixava rastro em lugar nenhum. O
-- capital_ledger deliberadamente NÃO registra essa transição (migration
-- 006: os dois estados comprometem capital, então não há movimento de
-- capital a lançar — e poluir o ledger com eventos de valor zero quebraria
-- a reconstrução do saldo). O efeito colateral é que o ato de declarar um
-- tomador inadimplente — que tem consequência jurídica e reputacional —
-- acontecia sem que ninguém soubesse quem o praticou.
--
-- Daí a separação de responsabilidades:
--   capital_ledger    -> movimentos de CAPITAL (hash-chain, reconstrói saldo)
--   operacao_evento   -> transições de ESTADO (quem, quando, por quê)
--
-- São trilhas diferentes porque respondem a perguntas diferentes. Fundi-las
-- obrigaria a inventar valores para eventos que não movem dinheiro.
--
-- Novo SQLSTATE: OC010 = tentativa de alterar/apagar evento de operação.

-- ---------------------------------------------------------------------
-- Trilha de transições de estado
-- ---------------------------------------------------------------------
create table if not exists operacao_evento (
    id               uuid primary key default uuid_generate_v4(),
    operacao_id      uuid not null references operacao_credito(id),
    status_anterior  text,
    status_novo      text not null,
    origem           text not null,
    usuario_id       text,
    dias_atraso      int,
    -- clock_timestamp(), NÃO now(): `now()` devolve o instante de início da
    -- TRANSAÇÃO, igual para todos os eventos gravados dentro dela. Numa
    -- trilha cujo propósito é mostrar a sequência dos atos, isso empata as
    -- linhas de uma novação (baixa + substituta) e a ordem exibida vira
    -- arbitrária. clock_timestamp() lê o relógio a cada statement.
    created_at       timestamp not null default clock_timestamp(),
    constraint operacao_evento_origem_valida check (origem in ('usuario', 'sistema')),
    -- O que a régua automática faz nunca pode ser atribuído a uma pessoa:
    -- se `origem = 'sistema'` carregasse um usuario_id, a trilha permitiria
    -- responsabilizar alguém por um ato que ela não praticou.
    constraint operacao_evento_sistema_sem_autor check (
        origem <> 'sistema' or usuario_id is null
    )
);

create index if not exists idx_operacao_evento_operacao on operacao_evento(operacao_id);
create index if not exists idx_operacao_evento_created on operacao_evento(created_at desc);

-- Append-only, como o capital_ledger: uma trilha que pode ser editada não
-- é trilha.
create or replace function fn_operacao_evento_append_only()
returns trigger as $$
begin
    raise exception 'operacao_evento é append-only: % não é permitido.', tg_op
        using errcode = 'OC010';
end;
$$ language plpgsql;

drop trigger if exists trg_operacao_evento_append_only on operacao_evento;
create trigger trg_operacao_evento_append_only
    before update or delete on operacao_evento
    for each row execute function fn_operacao_evento_append_only();

-- ---------------------------------------------------------------------
-- Aging: derivado da agenda, nunca armazenado
-- ---------------------------------------------------------------------
-- Dias de atraso saem da parcela em aberto mais antiga já vencida. É
-- DERIVADO da agenda (imutável desde a 007), não uma coluna que alguém
-- atualiza — coluna denormalizada aqui envelheceria em silêncio e faria a
-- régua de cobrança decidir sobre um número errado.
create or replace function fn_dias_atraso(p_operacao_id uuid)
returns int as $$
declare
    v_vencimento date;
begin
    select min(vencimento) into v_vencimento
    from parcela
    where operacao_id = p_operacao_id
      and status = 'aberta'
      and vencimento < current_date;

    if v_vencimento is null then
        return 0;
    end if;
    return (current_date - v_vencimento)::int;
end;
$$ language plpgsql stable;

create or replace function fn_faixa_aging(p_dias int)
returns text as $$
begin
    return case
        when p_dias <= 0  then 'em_dia'
        when p_dias <= 30 then 'ate_30'
        when p_dias <= 60 then 'de_31_a_60'
        when p_dias <= 90 then 'de_61_a_90'
        else 'acima_de_90'
    end;
end;
$$ language plpgsql immutable;

-- Só operações que comprometem capital entram no aging: proposta e
-- registrada não têm agenda, liquidada e cancelada não têm o que cobrar.
create or replace view v_aging_operacoes as
select
    oc.id                as operacao_id,
    oc.status,
    oc.valor_principal,
    t.id                 as tomador_id,
    t.razao_social       as tomador_razao_social,
    fn_dias_atraso(oc.id) as dias_atraso,
    fn_faixa_aging(fn_dias_atraso(oc.id)) as faixa,
    (select count(*) from parcela p
      where p.operacao_id = oc.id and p.status = 'aberta'
        and p.vencimento < current_date) as parcelas_vencidas,
    coalesce((select sum(p.valor_total) from parcela p
      where p.operacao_id = oc.id and p.status = 'aberta'
        and p.vencimento < current_date), 0) as valor_vencido
from operacao_credito oc
join tomador t on t.id = oc.tomador_id
where oc.status in ('ativa', 'inadimplente');

-- ---------------------------------------------------------------------
-- Registro automático de toda transição de estado
-- ---------------------------------------------------------------------
-- Reaproveita `app.user_id`, o mesmo setting que a migration 004 já usa
-- para o autor no capital_ledger — uma só convenção de propagação de autor
-- em todo o motor.
--
-- `app.origem = 'sistema'` marca o que a régua automática fez. Fora disso,
-- a transição é atribuída a uma pessoa; se `app.user_id` não veio, o autor
-- fica nulo, exatamente como já acontece no capital_ledger (a trilha segue
-- registrando o QUE aconteceu mesmo sem saber QUEM — melhor do que não
-- registrar).
create or replace function fn_registrar_evento_operacao()
returns trigger as $$
declare
    v_origem  text;
    v_usuario text;
begin
    if tg_op = 'UPDATE' and new.status is not distinct from old.status then
        return null;
    end if;

    v_origem := case
        when coalesce(current_setting('app.origem', true), '') = 'sistema' then 'sistema'
        else 'usuario'
    end;
    v_usuario := case
        when v_origem = 'sistema' then null
        else nullif(current_setting('app.user_id', true), '')
    end;

    insert into operacao_evento (
        operacao_id, status_anterior, status_novo, origem, usuario_id, dias_atraso
    ) values (
        new.id,
        case when tg_op = 'UPDATE' then old.status else null end,
        new.status,
        v_origem,
        v_usuario,
        fn_dias_atraso(new.id)
    );
    return null;
end;
$$ language plpgsql;

drop trigger if exists trg_registrar_evento_operacao on operacao_credito;
create trigger trg_registrar_evento_operacao
    after insert or update on operacao_credito
    for each row execute function fn_registrar_evento_operacao();

-- ---------------------------------------------------------------------
-- Régua automática
-- ---------------------------------------------------------------------
-- PARÂMETRO DE NEGÓCIO: 90 dias. A LC 167/2019 não fixa prazo; 90 dias é a
-- marca clássica de "curso anormal" da Res. CMN 2.682 e serve de padrão
-- defensável. É parâmetro da função justamente para a ESC poder adotar
-- outro prazo sem alterar a lógica.
--
-- Só mexe em 'ativa' -> 'inadimplente'. Nunca faz o caminho de volta: a
-- regularização é decisão de uma pessoa, com nome na trilha. Uma régua que
-- reativasse sozinha ao ver a parcela baixada tiraria do humano a
-- confirmação de que o dinheiro entrou de fato.
--
-- Idempotente: rodar duas vezes no mesmo dia não gera evento novo, porque
-- na segunda passada as operações já saíram de 'ativa'.
create or replace function fn_processar_aging(p_limite_dias int default 90)
returns int as $$
declare
    v_id    uuid;
    v_total int := 0;
begin
    perform set_config('app.origem', 'sistema', true);

    for v_id in
        select oc.id
        from operacao_credito oc
        where oc.status = 'ativa'
          and fn_dias_atraso(oc.id) >= p_limite_dias
        order by oc.id
    loop
        update operacao_credito set status = 'inadimplente', updated_at = now()
        where id = v_id;
        v_total := v_total + 1;
    end loop;

    -- Devolve a conexão ao estado normal: sem isso, uma transição feita
    -- por uma pessoa depois desta chamada, na MESMA transação, seria
    -- gravada como se o sistema a tivesse praticado.
    perform set_config('app.origem', '', true);
    return v_total;
end;
$$ language plpgsql;
