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

-- Comentários de documentação
comment on table tomador is 'Tomadores de crédito: pessoas jurídicas enquadráveis em ESC (ME/EPP)';
comment on table operacao_credito is 'Operações de crédito: ciclo de vida (proposta → ativa → liquidada/inadimplente)';
comment on table esc_capital_social is 'Histórico de capital social (constituição e reduções)';
comment on table capital_ledger is 'Ledger imutável de movimentações: ativação, liquidação, amortização';
comment on column operacao_credito.registro_entidade_ref is 'Referência de registro em entidade apodada (Art. 5º §3º, LC 167/2019)';
comment on column operacao_credito.status is 'Estados: proposta, registrada, ativa, liquidada, inadimplente, renegociada, cancelada';
