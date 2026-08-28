-- OrgCred — o portal do tomador: um login que vê só o que é dele
--
-- Até aqui `usuario` era só o painel da ESC (papel admin/operador). O tomador —
-- a empresa que pegou o crédito — não tinha login: acompanhava a operação por
-- fora do sistema. Este é o vínculo que falta, e ele é de IDENTIDADE, então
-- mora no banco e não na aplicação.
--
-- ---------------------------------------------------------------------
-- O PAPEL NOVO, E A AMARRA QUE O TORNA COERENTE
-- ---------------------------------------------------------------------
-- `usuario.papel` ganha 'tomador', e `usuario` ganha `tomador_id`. Os dois não
-- são independentes: um login de tomador SEM tomador apontado não vê nada e não
-- deveria existir; um login de painel (admin/operador) COM tomador apontado
-- seria um operador que também é cliente de si mesmo — exatamente o tipo de
-- confusão de papéis que a segregação existe para impedir. O CHECK abaixo é a
-- regra, e é o banco que a garante:
--
--   papel = 'tomador'            <-> tomador_id NÃO nulo
--   papel in ('admin','operador') <-> tomador_id nulo
--
-- Sem esta amarra, um bug de aplicação que criasse um usuário 'operador' com
-- tomador_id preenchido — ou um 'tomador' sem vínculo — passaria despercebido
-- até virar vazamento de dados. Com ela, o estado incoerente é recusado no
-- INSERT, com OC027, e a aplicação não tem como produzi-lo nem por engano.
alter table usuario
    add column if not exists tomador_id uuid references tomador(id);

comment on column usuario.tomador_id is
    'Para papel=tomador, a empresa cujo painel este login enxerga. NULO para admin/operador. O CHECK usuario_papel_vinculo_coerente garante os dois lados.';

alter table usuario
    drop constraint if exists usuario_papel_valido;
alter table usuario
    add constraint usuario_papel_valido
    check (papel in ('admin', 'operador', 'tomador'));

alter table usuario
    drop constraint if exists usuario_papel_vinculo_coerente;
alter table usuario
    add constraint usuario_papel_vinculo_coerente
    check (
        (papel = 'tomador' and tomador_id is not null)
        or (papel in ('admin', 'operador') and tomador_id is null)
    );

comment on constraint usuario_papel_vinculo_coerente on usuario is
    'Tomador tem vínculo; painel não tem. Um operador que fosse cliente de si mesmo é a confusão de papéis que a segregação existe para impedir.';

-- Um mesmo tomador pode ter mais de um login (o sócio e o contador da empresa,
-- por exemplo), então NÃO há unique sobre tomador_id — o índice é só para a
-- consulta "os logins desta empresa" e para o filtro de escopo do portal, que
-- roda a cada request.
create index if not exists idx_usuario_tomador on usuario(tomador_id)
    where tomador_id is not null;

-- ---------------------------------------------------------------------
-- A TRILHA DO PROVISIONAMENTO É APPEND-ONLY, como as outras
-- ---------------------------------------------------------------------
-- Convidar um tomador para o portal é dar a um CNPJ externo uma janela para os
-- dados de crédito dele. Quem convidou quem, e quando, é prova de conformidade
-- (Lei 9.613/98, dever de identificação) — e prova que se edita não é prova. A
-- trilha reusa a guarda de append-only que a 016 instalou nas outras cinco
-- tabelas, com um SQLSTATE próprio porque a instrução ao operador é outra.
create table if not exists convite_portal (
    id uuid primary key default uuid_generate_v4(),
    tomador_id uuid not null references tomador(id),
    email text not null,
    convidado_por text,          -- usuario.id de quem convidou (app.user_id)
    usuario_id uuid references usuario(id),  -- preenchido quando o convite vira login
    criado_em timestamp without time zone not null default clock_timestamp(),
    aceito_em timestamp without time zone
);

comment on table convite_portal is
    'Trilha append-only de convites ao portal do tomador. Só `usuario_id` e `aceito_em` podem ser preenchidos depois, quando o convidado ativa o login — o resto é a prova de quem abriu a janela e quando.';

create index if not exists idx_convite_tomador on convite_portal(tomador_id);

create or replace function fn_convite_portal_imutavel()
returns trigger as $$
begin
    if tg_op = 'DELETE' then
        raise exception
            'Convite de portal % não pode ser apagado: a trilha de quem recebeu acesso é append-only.',
            old.id
            using errcode = 'OC027';
    end if;

    -- Só o par (usuario_id, aceito_em) pode passar de nulo a preenchido, uma
    -- vez, quando o convite vira login. Todo o resto é imutável — a mesma
    -- disciplina de `ocorrencia_atipicidade` (014).
    if new.tomador_id is distinct from old.tomador_id
       or new.email is distinct from old.email
       or new.convidado_por is distinct from old.convidado_por
       or new.criado_em is distinct from old.criado_em
       or (old.usuario_id is not null and new.usuario_id is distinct from old.usuario_id)
       or (old.aceito_em is not null and new.aceito_em is distinct from old.aceito_em) then
        raise exception
            'Convite de portal % é append-only: só o vínculo do login e a data de aceite se preenchem, uma vez.',
            old.id
            using errcode = 'OC027';
    end if;

    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_convite_portal_imutavel on convite_portal;
create trigger trg_convite_portal_imutavel
    before update or delete on convite_portal
    for each row execute function fn_convite_portal_imutavel();

drop trigger if exists trg_bloquear_truncate_convite on convite_portal;
create trigger trg_bloquear_truncate_convite
    before truncate on convite_portal
    for each statement execute function fn_bloquear_truncate_append_only('OC027');

comment on function fn_convite_portal_imutavel() is
    'OC027 — a trilha de convites ao portal é append-only; só o vínculo do login e a data de aceite se preenchem depois.';
