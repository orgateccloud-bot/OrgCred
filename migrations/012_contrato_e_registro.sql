-- OrgCred — instrumento contratual e registro na entidade registradora
--
-- O QUE ESTA MIGRATION RESOLVE
--
-- `operacao_credito.registro_entidade_ref` é TEXTO LIVRE. O trigger OC004
-- só verifica que o campo não está vazio: escrever "x" ali passa pelo gate
-- do Art. 5º §3º da LC 167/2019. O registro na entidade registradora é
-- condição legal para a operação existir, e hoje o sistema aceita qualquer
-- string como prova de que ele aconteceu.
--
-- Duas peças, ambas independentes de QUAL registradora será escolhida:
--
--   1. `contrato_emprestimo` — o instrumento em si, gerado a partir dos
--      dados da operação e da agenda de parcelas, imutável depois de
--      emitido (OC017).
--   2. `registro_operacao` — o registro como entidade de primeira classe:
--      entidade, protocolo, status e datas, com adaptador plugável.
--
-- TIPO DO INSTRUMENTO: "Contrato de Empréstimo ESC", não CCB. A CCB
-- (Lei 10.931/2004) é instrumento de instituição financeira, e uma ESC não
-- é. A própria pesquisa de registradoras (PESQUISA_ENTIDADE_REGISTRADORA.md)
-- mostra a CRDC tratando "Contratos ESC" como categoria de ativo SEPARADA
-- de CCB — o que confirma que não são a mesma coisa. `tipo_instrumento` é
-- coluna justamente para o advogado poder mudar isso sem migration nova.
--
-- O GATE FICA DESLIGADO. Exigir registro CONFIRMADO para ativar é a amarra
-- com dentes, mas mudaria comportamento: operações com referência inventada
-- parariam de ativar. A view `v_operacoes_sem_registro_confirmado` mostra
-- quantas e quanto, para a decisão ser tomada com o número na mão. O trigger
-- que ligaria o gate está escrito ao final deste arquivo, comentado.
--
-- Novos SQLSTATEs:
--   OC017 = instrumento contratual é imutável
--   OC018 = transição inválida de status de registro

-- ---------------------------------------------------------------------
-- 1. Instrumento contratual
-- ---------------------------------------------------------------------
-- O corpo é gerado pela aplicação (é texto, não regra de negócio), mas o
-- HASH é calculado pelo BANCO no INSERT. Assim corpo e hash não podem
-- divergir nem ser forjados: quem escrever direto no banco também terá o
-- hash do que escreveu, e a conferência posterior denuncia a diferença.
create table if not exists contrato_emprestimo (
    id                uuid primary key default uuid_generate_v4(),
    operacao_id       uuid not null references operacao_credito(id),
    versao            int not null default 1,
    tipo_instrumento  text not null default 'contrato_emprestimo_esc',
    corpo             text not null,
    sha256            char(64) not null,
    emitido_em        timestamp not null default clock_timestamp(),
    usuario_id        text,
    constraint contrato_versao_unica unique (operacao_id, versao),
    constraint contrato_corpo_nao_vazio check (length(corpo) > 0)
);

create index if not exists idx_contrato_operacao on contrato_emprestimo(operacao_id);

create or replace function fn_contrato_hash()
returns trigger as $$
begin
    new.sha256 := encode(digest(new.corpo, 'sha256'), 'hex');
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_contrato_hash on contrato_emprestimo;
create trigger trg_contrato_hash
    before insert on contrato_emprestimo
    for each row execute function fn_contrato_hash();

-- Imutável: reemitir gera uma nova versão. Editar o corpo de um contrato já
-- emitido destruiria a prova do que foi efetivamente acordado — e o
-- tomador tem uma via do documento antigo.
create or replace function fn_contrato_imutavel()
returns trigger as $$
begin
    raise exception
        'Instrumento contratual é imutável: reemitir cria uma nova versão.'
        using errcode = 'OC017';
end;
$$ language plpgsql;

drop trigger if exists trg_contrato_imutavel on contrato_emprestimo;
create trigger trg_contrato_imutavel
    before update or delete on contrato_emprestimo
    for each row execute function fn_contrato_imutavel();

-- Última versão de cada operação — é o contrato vigente.
create or replace view v_contrato_vigente as
select distinct on (operacao_id) *
from contrato_emprestimo
order by operacao_id, versao desc;

-- ---------------------------------------------------------------------
-- 2. Registro na entidade registradora
-- ---------------------------------------------------------------------
-- `entidade` é texto e não enum: a escolha entre CRDC, Núclea, SPC Grafeno,
-- B3 e CERC não foi feita, e um enum obrigaria migration a cada mudança de
-- fornecedor — inclusive durante um piloto com duas em paralelo.
create table if not exists registro_operacao (
    id             uuid primary key default uuid_generate_v4(),
    operacao_id    uuid not null references operacao_credito(id),
    entidade       text not null,
    protocolo      text,
    status         text not null default 'pendente',
    enviado_em     timestamp not null default clock_timestamp(),
    confirmado_em  timestamp,
    motivo_rejeicao text,
    usuario_id     text,
    constraint registro_status_valido check (status in ('pendente', 'confirmado', 'rejeitado')),
    -- Confirmado exige protocolo: registro confirmado sem número de
    -- protocolo é indistinguível de alguém marcando a caixinha.
    constraint registro_confirmado_tem_protocolo check (
        status <> 'confirmado' or (protocolo is not null and confirmado_em is not null)
    ),
    constraint registro_rejeitado_tem_motivo check (
        status <> 'rejeitado' or motivo_rejeicao is not null
    )
);

create index if not exists idx_registro_operacao on registro_operacao(operacao_id);

-- Só UM registro confirmado por operação. Dois confirmados significariam a
-- mesma operação registrada duas vezes — e nenhum sistema saberia qual vale.
create unique index if not exists idx_registro_confirmado_unico
    on registro_operacao(operacao_id) where status = 'confirmado';

-- Máquina de estados: 'pendente' é o único ponto de partida, e confirmado
-- ou rejeitado são terminais. Reverter um registro confirmado apagaria a
-- prova de que a operação existe legalmente.
create or replace function fn_registro_transicao()
returns trigger as $$
begin
    if tg_op = 'DELETE' then
        raise exception 'Registro de operação não pode ser apagado.'
            using errcode = 'OC018';
    end if;

    if old.status <> 'pendente' then
        raise exception
            'Registro já está % — é estado terminal.', old.status
            using errcode = 'OC018';
    end if;

    if new.operacao_id is distinct from old.operacao_id
       or new.entidade is distinct from old.entidade
       or new.enviado_em is distinct from old.enviado_em then
        raise exception
            'Operação, entidade e data de envio do registro são imutáveis.'
            using errcode = 'OC018';
    end if;

    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_registro_transicao on registro_operacao;
create trigger trg_registro_transicao
    before update or delete on registro_operacao
    for each row execute function fn_registro_transicao();

-- ---------------------------------------------------------------------
-- 3. A lacuna, medida
-- ---------------------------------------------------------------------
-- Operações que comprometem capital (ou estão prontas para comprometer)
-- sem registro CONFIRMADO. É o número que embasa a decisão de ligar o gate.
create or replace view v_operacoes_sem_registro_confirmado as
select
    oc.id as operacao_id,
    oc.status,
    oc.valor_principal,
    oc.registro_entidade_ref,
    t.razao_social as tomador_razao_social,
    exists (select 1 from registro_operacao r
             where r.operacao_id = oc.id and r.status = 'pendente') as tem_registro_pendente,
    exists (select 1 from contrato_emprestimo c where c.operacao_id = oc.id) as tem_contrato
from operacao_credito oc
join tomador t on t.id = oc.tomador_id
where oc.status in ('registrada', 'ativa', 'inadimplente')
  and not exists (
      select 1 from registro_operacao r
      where r.operacao_id = oc.id and r.status = 'confirmado'
  );

-- ---------------------------------------------------------------------
-- 4. O gate, escrito e DESLIGADO
-- ---------------------------------------------------------------------
-- Ligar isto substitui a checagem de texto livre da migration 001 (OC004)
-- por exigência de registro confirmado de verdade. Deixado como comentário
-- porque mudaria comportamento: operações já ativas com referência inventada
-- não seriam afetadas (o trigger só roda na transição), mas as que estão em
-- 'registrada' parariam de ativar até haver registro confirmado.
--
-- Antes de ligar, medir com: select * from v_operacoes_sem_registro_confirmado;
--
--   create or replace function fn_check_registro_confirmado()
--   returns trigger as $$
--   begin
--       if new.status = 'ativa' and old.status is distinct from 'ativa'
--          and not exists (
--              select 1 from registro_operacao r
--              where r.operacao_id = new.id and r.status = 'confirmado'
--          ) then
--           raise exception
--               'Operação % não tem registro confirmado em entidade registradora (Art. 5º §3º, LC 167/2019).',
--               new.id using errcode = 'OC004';
--       end if;
--       return new;
--   end;
--   $$ language plpgsql;
--
--   create trigger trg_check_registro_confirmado
--       before update on operacao_credito
--       for each row execute function fn_check_registro_confirmado();
