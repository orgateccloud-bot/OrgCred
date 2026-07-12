-- OrgCred — integridade do capital_ledger (Fase 7 da modernização)
--
-- Duas melhorias, ambas puramente técnicas (sem decisão de negócio
-- pendente — ver DECISOES_PENDENTES.md):
--
--   1. Proteção append-only: capital_ledger é conceitualmente imutável
--      desde a criação (migration 001), mas nada impedia UPDATE/DELETE
--      acidental. Um ledger que pode ser silenciosamente alterado não é
--      prova de conformidade com o teto legal (Art. 5º, LC 167/2019) — é
--      só um log que parece confiável.
--
--   2. Hash-chain: cada linha referencia o hash da anterior, permitindo
--      detectar adulteração retroativa mesmo que alguém tenha acesso
--      direto ao banco (ex. um DBA malicioso, ou uma restauração de
--      backup fora de ordem). Não substitui backup/WAL — é uma camada
--      adicional de evidência de integridade.

-- ---------------------------------------------------------------------
-- 1. Proteção append-only
-- ---------------------------------------------------------------------
create or replace function fn_bloquear_mutacao_ledger()
returns trigger as $$
begin
    raise exception
        'capital_ledger é append-only: % não é permitido (linha %).',
        tg_op, coalesce(old.id, new.id)
        using errcode = 'OC007';
end;
$$ language plpgsql;

create trigger trg_bloquear_update_ledger
    before update on capital_ledger
    for each row execute function fn_bloquear_mutacao_ledger();

create trigger trg_bloquear_delete_ledger
    before delete on capital_ledger
    for each row execute function fn_bloquear_mutacao_ledger();

-- ---------------------------------------------------------------------
-- 2. Hash-chain
-- ---------------------------------------------------------------------
alter table capital_ledger
    add column if not exists prev_hash    varchar(64),
    add column if not exists current_hash varchar(64);

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

create extension if not exists pgcrypto;

create trigger trg_calcular_hash_ledger
    before insert on capital_ledger
    for each row execute function fn_calcular_hash_ledger();

comment on column capital_ledger.prev_hash is
    'Hash SHA-256 da linha anterior da cadeia — permite detectar adulteração retroativa.';
comment on column capital_ledger.current_hash is
    'Hash SHA-256 desta linha (inclui prev_hash) — recalculável para validar integridade.';

-- ---------------------------------------------------------------------
-- 3. Verificação da cadeia — sem isso o hash-chain é só decoração.
--    Recalcula o hash de cada linha e compara com o current_hash
--    armazenado, e confere que prev_hash bate com o current_hash da
--    linha anterior na ordem cronológica. Retorna as linhas QUEBRADAS
--    (0 linhas = cadeia íntegra).
-- ---------------------------------------------------------------------
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

comment on function fn_verificar_cadeia_ledger() is
    'Recalcula e valida a cadeia de hash do capital_ledger. SELECT * FROM fn_verificar_cadeia_ledger() — 0 linhas = íntegro.';
