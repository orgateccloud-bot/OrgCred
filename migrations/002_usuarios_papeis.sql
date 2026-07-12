-- OrgCred — Usuários e papéis de acesso
-- Cria tabela de usuários com papéis (admin/operador)

create table if not exists usuario (
    id uuid primary key default uuid_generate_v4(),
    email varchar(255) unique not null,
    nome varchar(255) not null,
    papel varchar(20) not null,  -- admin, operador
    ativo boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_usuario_email on usuario(email);
create index if not exists idx_usuario_papel on usuario(papel);

comment on table usuario is 'Usuários do painel de operações da ESC';
comment on column usuario.papel is 'admin: acesso total; operador: ativa operações dentro do limite de capital';
