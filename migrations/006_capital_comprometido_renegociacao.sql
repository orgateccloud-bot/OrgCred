-- OrgCred — capital comprometido coerente + suporte à renegociação (novação)
--
-- Esta migration fecha DOIS furos no motor de capital, ambos da mesma
-- classe das falhas F1–F3 corrigidas na 003 (integridade do teto do
-- Art. 5º, LC 167/2019), e prepara o banco para o fluxo de renegociação
-- (REVISAO_2026-07-11.md, item 3: "Fluxo de renegociação indefinido"):
--
--   G1. Marcar uma operação como 'inadimplente' LIBERAVA capital: o
--       comprometimento era calculado como sum(valor_principal) where
--       status = 'ativa', então a transição ativa -> inadimplente (o ato
--       operacional esperado para um atraso) abria teto para novas
--       ativações enquanto o dinheiro da operação em atraso continuava na
--       rua — permitindo, por um caminho honesto, contratar acima do
--       capital social. Isso contradiz a interpretação conservadora já
--       documentada do projeto ("usa valor_principal integral até
--       liquidação" — ver DECISOES_PENDENTES.md).
--   G2. A transição -> 'renegociada' liberava capital SEM evento no
--       ledger e sem lock: a trilha de auditoria mostrava a ativação da
--       operação mas nunca a sua saída do conjunto comprometido.
--
-- Regra após esta migration:
--
--   CONJUNTO COMPROMETIDO = operações em status ('ativa', 'inadimplente').
--   Eventos de ledger acontecem SOMENTE na fronteira do conjunto:
--     entrada:  registrada -> ativa            => 'ativacao_operacao'
--     saída:    ativa|inadimplente -> liquidada => 'liquidacao'
--               ativa|inadimplente -> renegociada => 'renegociacao_liberacao'
--   Movimentos INTERNOS ao conjunto não geram evento nem re-execução de
--   gates: ativa -> inadimplente e inadimplente -> ativa (regularização)
--   não movem capital — antes desta migration a regularização re-rodava o
--   gate completo (incl. teto) e gravava um 'ativacao_operacao' duplicado
--   no ledger, sem capital novo ter sido comprometido.
--
-- A definição de comprometimento é centralizada em
-- fn_capital_comprometido(), usada pelo trigger de operação, pelo trigger
-- de redução de capital e pela API (app/capital_engine.py) — três lugares
-- que antes duplicavam o mesmo SUM e podiam divergir silenciosamente.
--
-- Nota: a versão anterior tratava ativa -> cancelada como liquidação no
-- ledger, mas essa transição sempre foi inválida na máquina de estados
-- (OC003 dispara antes) — o ramo era código morto e foi removido.

-- ---------------------------------------------------------------------
-- 1. Fonte única da definição de capital comprometido
-- ---------------------------------------------------------------------
create or replace function fn_capital_comprometido(p_excluir uuid default null)
returns numeric as $$
    select coalesce(sum(valor_principal), 0)
    from operacao_credito
    where status in ('ativa', 'inadimplente')
      and (p_excluir is null or id <> p_excluir);
$$ language sql stable;

comment on function fn_capital_comprometido(uuid) is
    'Total de valor_principal comprometido (status ativa ou inadimplente). '
    'p_excluir remove uma operação do cálculo — usado pelos triggers BEFORE, '
    'onde a linha em transição ainda tem o status antigo na tabela.';

-- ---------------------------------------------------------------------
-- 2. Trigger de operação reescrito (fronteira do conjunto comprometido)
-- ---------------------------------------------------------------------
create or replace function fn_check_teto_capital()
returns trigger as $$
declare
    v_capital_atual  numeric(14,2);
    v_disponivel     numeric(14,2);
    v_municipio_ok   boolean;
    v_usuario_id     text;
    v_evento         varchar(50);
begin
    v_usuario_id := nullif(current_setting('app.user_id', true), '');

    -- Máquina de estados (inalterada desde a 003):
    --   proposta     -> registrada | cancelada
    --   registrada   -> ativa | cancelada
    --   ativa        -> liquidada | inadimplente | renegociada
    --   inadimplente -> ativa | renegociada | liquidada
    --   renegociada | liquidada | cancelada -> (terminais)
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

    -- ENTRADA no conjunto comprometido: somente registrada -> ativa.
    -- (INSERT já em 'ativa' é barrado acima; inadimplente -> ativa é
    -- regularização — o capital já estava comprometido, nada muda e
    -- nenhum gate re-executa, preservando a idempotência do ledger.)
    if tg_op = 'UPDATE' and old.status = 'registrada' and new.status = 'ativa' then

        -- F1 (003): serializa toda movimentação de capital. Advisory lock
        -- transacional global — aceitável em single-tenant, ativação não é
        -- caminho de alto throughput neste negócio.
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
        v_disponivel := v_capital_atual - fn_capital_comprometido(new.id);

        if new.valor_principal > v_disponivel then
            raise exception
                'Teto de capital excedido (Art. 5º, LC 167/2019). Capital disponível: %, valor solicitado: %. Operação % bloqueada.',
                v_disponivel, new.valor_principal, new.id
                using errcode = 'OC001';
        end if;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values ('ativacao_operacao', new.valor_principal, new.id,
                v_disponivel - new.valor_principal, v_usuario_id);
    end if;

    -- SAÍDA do conjunto comprometido: libera capital e registra no ledger,
    -- sob o mesmo lock (o saldo gravado precisa ser consistente com
    -- ativações concorrentes). É este lock, tomado no primeiro passo da
    -- novação (antiga -> renegociada), que serializa a renegociação
    -- inteira contra qualquer outra movimentação de capital.
    if tg_op = 'UPDATE'
       and old.status in ('ativa','inadimplente')
       and new.status in ('liquidada','renegociada') then

        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        v_evento := case when new.status = 'liquidada'
                         then 'liquidacao'
                         else 'renegociacao_liberacao' end;

        select capital_atual into v_capital_atual from v_capital_atual;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values (v_evento, new.valor_principal, new.id,
                v_capital_atual - fn_capital_comprometido(new.id), v_usuario_id);
    end if;

    new.updated_at := now();
    return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- 3. Hash-chain do ledger com ordem determinística (pré-requisito da
--    novação)
--
--    A 005 ordena a cadeia por (created_at, id) — mas now() é fixo por
--    transação, e a novação grava DOIS eventos na mesma transação
--    ('renegociacao_liberacao' + 'ativacao_operacao') com created_at
--    idêntico e ids UUID aleatórios: o escritor e o verificador
--    desempatariam por UUID e a cadeia seria reportada como adulterada
--    de forma intermitente. Nunca se manifestou antes porque cada
--    transação gravava no máximo um evento. Correção: coluna `seq`
--    (identity, monotônica na ordem real de inserção) como desempate.
--    A ordem passa a ser (created_at, seq): preserva a cadeia de linhas
--    pré-existentes (que nunca compartilham created_at) e é
--    determinística dentro de uma mesma transação. O hash em si não
--    muda de fórmula — nenhuma linha existente precisa ser recalculada.
-- ---------------------------------------------------------------------
alter table capital_ledger
    add column if not exists seq bigint generated always as identity;

create unique index if not exists idx_capital_ledger_seq on capital_ledger(seq);

create or replace function fn_calcular_hash_ledger()
returns trigger as $$
declare
    v_prev_hash varchar(64);
begin
    select current_hash into v_prev_hash
    from capital_ledger
    order by created_at desc, seq desc
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
            lag(l.current_hash) over (order by l.created_at, l.seq) as hash_anterior_esperado
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

-- ---------------------------------------------------------------------
-- 4. Redução de capital vigiada — agora contra o comprometido REAL
--    (ativa + inadimplente), pela mesma fonte única
-- ---------------------------------------------------------------------
create or replace function fn_check_reducao_capital()
returns trigger as $$
declare
    v_capital_pos_reducao   numeric(14,2);
    v_comprometido          numeric(14,2);
begin
    if new.tipo_evento = 'reducao' then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual - new.valor into v_capital_pos_reducao from v_capital_atual;
        v_comprometido := fn_capital_comprometido();

        if v_capital_pos_reducao < v_comprometido then
            raise exception
                'Redução de capital bloqueada: capital resultante (%) ficaria abaixo do total comprometido em operações ativas/inadimplentes (%). Art. 5º, LC 167/2019.',
                v_capital_pos_reducao, v_comprometido
                using errcode = 'OC005';
        end if;
    end if;
    return new;
end;
$$ language plpgsql;
