-- OrgCred — Schema inicial
-- Cria tabelas base e view de capital disponível
-- LC 167/2019 — Empresa Simples de Crédito

create extension if not exists "uuid-ossp";

-- Tabela de tomadores de crédito
create table if not exists tomador (
    id uuid primary key default uuid_generate_v4(),
    cnpj varchar(14) unique not null,
    razao_social varchar(255) not null,
    porte varchar(10) not null,  -- ME, EPP, etc.
    municipio varchar(255) not null,
    uf varchar(2) not null,
    municipio_autorizado boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Tabela de operações de crédito
create table if not exists operacao_credito (
    id uuid primary key default uuid_generate_v4(),
    tomador_id uuid not null references tomador(id),
    tipo varchar(20) not null,  -- emprestimo, financiamento
    valor_principal numeric(14, 2) not null,
    taxa_juros_mensal numeric(5, 2) not null,
    sistema_amortizacao varchar(10) not null,  -- PRICE, SAC
    numero_parcelas integer not null,
    status varchar(20) not null default 'proposta',
    registro_entidade_ref varchar(255),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_operacao_credito_tomador_id on operacao_credito(tomador_id);
create index if not exists idx_operacao_credito_status on operacao_credito(status);

-- Tabela de capital social (histórico)
create table if not exists esc_capital_social (
    id uuid primary key default uuid_generate_v4(),
    valor numeric(14, 2) not null,
    tipo_evento varchar(50) not null,  -- constituicao, reducao
    created_at timestamptz not null default now()
);

-- Ledger imutável de movimentações de capital
create table if not exists capital_ledger (
    id uuid primary key default uuid_generate_v4(),
    evento_tipo varchar(50) not null,  -- ativacao_operacao, liquidacao, amortizacao, etc.
    valor numeric(14, 2) not null,
    operacao_id uuid references operacao_credito(id),
    saldo_disponivel_pos numeric(14, 2) not null,
    usuario_id varchar(255),
    created_at timestamptz not null default now()
);

create index if not exists idx_capital_ledger_operacao_id on capital_ledger(operacao_id);
create index if not exists idx_capital_ledger_evento_tipo on capital_ledger(evento_tipo);

-- View: capital atual (último constituição/redução)
create or replace view v_capital_atual as
select coalesce(sum(
    case when tipo_evento = 'constituicao' then valor
         when tipo_evento = 'reducao' then -valor
         else 0
    end
), 0) as capital_atual
from esc_capital_social;

-- Trigger do teto de capital (versão original, pré-hardening).
--
-- ATENÇÃO: esta versão tem a race condition F1 documentada em
-- REVISAO_2026-07-11.md (SELECT SUM sem lock: duas ativações concorrentes
-- podem ambas passar pelo teto). A migration 003_hardening_capital.sql
-- substitui o CORPO desta função (CREATE OR REPLACE) com o advisory lock
-- e a máquina de estados — mas o TRIGGER em si é criado aqui e nunca é
-- recriado por 003, então precisa existir desde a migration 001.
create or replace function fn_check_teto_capital()
returns trigger as $$
declare
    v_capital_atual         numeric(14,2);
    v_comprometido_outras   numeric(14,2);
    v_disponivel            numeric(14,2);
    v_municipio_ok          boolean;
begin
    if new.status = 'ativa' and (tg_op = 'INSERT' or old.status is distinct from 'ativa') then
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

    new.updated_at := now();
    return new;
end;
$$ language plpgsql;

create trigger trg_check_teto_capital
    before insert or update on operacao_credito
    for each row execute function fn_check_teto_capital();

-- Comentários de documentação
comment on table tomador is 'Tomadores de crédito: pessoas jurídicas enquadráveis em ESC (ME/EPP)';
comment on table operacao_credito is 'Operações de crédito: ciclo de vida (proposta → ativa → liquidada/inadimplente)';
comment on table esc_capital_social is 'Histórico de capital social (constituição e reduções)';
comment on table capital_ledger is 'Ledger imutável de movimentações: ativação, liquidação, amortização';
comment on column operacao_credito.registro_entidade_ref is 'Referência de registro em entidade apodada (Art. 5º §3º, LC 167/2019)';
comment on column operacao_credito.status is 'Estados: proposta, registrada, ativa, liquidada, inadimplente, renegociada, cancelada';
