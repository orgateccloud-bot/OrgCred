-- OrgCred — compliance PLD/FT: o que não depende de terceiro
--
-- O regime PLD/COAF aplicável a uma ESC ainda depende de parecer jurídico
-- (ver MAPEAMENTO_E_PLANO_DE_COMBATE.md, Frente 4). O que NÃO depende de
-- ninguém, e por isso é construído aqui:
--
--   1. Identificação do tomador com EVIDÊNCIA ARQUIVADA e verificável.
--   2. RETENÇÃO de 5 anos (Lei 9.613/98, art. 10, III).
--   3. DETECÇÃO INTERNA de atipicidade sobre os dados que já existem.
--
-- O canal externo (COAF) fica como ADAPTADOR: a ocorrência é registrada com
-- um campo de comunicação que nada preenche hoje. Quando o parecer sair,
-- liga-se o envio sem mexer na detecção — e o histórico anterior continua
-- válido, porque já está gravado.
--
-- O QUE ESTA MIGRATION DELIBERADAMENTE NÃO FAZ: bloquear a ativação de
-- operações de tomador sem identificação arquivada. Seria a amarra com
-- dentes, mas é DECISÃO DE NEGÓCIO — hoje existem tomadores cadastrados sem
-- evidência, e ligar o bloqueio sem aviso pararia a operação. A consulta
-- `v_tomadores_sem_identificacao` expõe a lacuna para que a decisão seja
-- tomada com o número na mão.
--
-- Novos SQLSTATEs:
--   OC013 = evidência de identificação dentro do prazo de retenção
--   OC014 = ocorrência de atipicidade é append-only

-- ---------------------------------------------------------------------
-- 1. Identificação com evidência arquivada
-- ---------------------------------------------------------------------
-- Guarda o HASH do arquivo, não o arquivo. O binário vive no storage; o
-- que o banco garante é que o documento apresentado depois é bit a bit o
-- mesmo que foi arquivado. Guardar o arquivo aqui inflaria o banco e não
-- acrescentaria garantia nenhuma.
create table if not exists tomador_documento (
    id            uuid primary key default uuid_generate_v4(),
    tomador_id    uuid not null references tomador(id),
    tipo          text not null,
    nome_arquivo  text not null,
    sha256        char(64) not null,
    arquivado_em  timestamp not null default clock_timestamp(),
    -- Materializada, não calculada na leitura: se o prazo legal mudar, os
    -- documentos já arquivados mantêm a regra vigente na época — que é o
    -- que se defende numa fiscalização.
    retencao_ate  date not null,
    usuario_id    text,
    constraint tomador_documento_tipo_valido check (
        tipo in ('contrato_social', 'cartao_cnpj', 'documento_socio',
                 'comprovante_endereco', 'procuracao', 'outro')
    ),
    constraint tomador_documento_sha256_hex check (sha256 ~ '^[0-9a-f]{64}$'),
    constraint tomador_documento_unico unique (tomador_id, sha256)
);

create index if not exists idx_tomador_documento_tomador on tomador_documento(tomador_id);

-- Retenção de 5 anos: Lei 9.613/98, art. 10, III. Apagar antes do prazo é
-- recusado pelo banco — a obrigação de guardar não pode depender de
-- ninguém lembrar dela.
create or replace function fn_documento_retencao()
returns trigger as $$
begin
    if tg_op = 'DELETE' then
        if old.retencao_ate >= current_date then
            raise exception
                'Documento % do tomador % está em retenção legal até % (Lei 9.613/98, art. 10, III).',
                old.nome_arquivo, old.tomador_id, old.retencao_ate
                using errcode = 'OC013';
        end if;
        return old;
    end if;

    raise exception 'Evidência de identificação não pode ser alterada, apenas substituída por nova.'
        using errcode = 'OC013';
end;
$$ language plpgsql;

drop trigger if exists trg_documento_retencao on tomador_documento;
create trigger trg_documento_retencao
    before update or delete on tomador_documento
    for each row execute function fn_documento_retencao();

create or replace view v_tomadores_sem_identificacao as
select t.id as tomador_id, t.cnpj, t.razao_social,
       coalesce(sum(oc.valor_principal) filter (
           where oc.status in ('ativa', 'inadimplente')), 0) as capital_exposto
from tomador t
left join operacao_credito oc on oc.tomador_id = t.id
where not exists (select 1 from tomador_documento d where d.tomador_id = t.id)
group by t.id, t.cnpj, t.razao_social;

-- ---------------------------------------------------------------------
-- 2. Detecção interna de atipicidade
-- ---------------------------------------------------------------------
create table if not exists ocorrencia_atipicidade (
    id            uuid primary key default uuid_generate_v4(),
    regra         text not null,
    severidade    text not null,
    tomador_id    uuid references tomador(id),
    operacao_id   uuid references operacao_credito(id),
    detalhe       text not null,
    -- Adaptador do canal externo: hoje nada preenche. Quando o regime
    -- PLD for definido, o envio grava aqui sem tocar na detecção.
    comunicado_em timestamp,
    comunicacao_ref text,
    created_at    timestamp not null default clock_timestamp(),
    constraint ocorrencia_severidade_valida check (severidade in ('baixa', 'media', 'alta'))
);

create index if not exists idx_ocorrencia_created on ocorrencia_atipicidade(created_at desc);

-- Idempotência da varredura: rodar duas vezes no mesmo dia não pode duplicar
-- a mesma ocorrência, senão o painel vira ruído e o analista para de olhar —
-- o pior resultado possível para um controle de PLD.
--
-- ÍNDICE COM coalesce, e não `unique (regra, tomador_id, operacao_id,
-- detalhe)`: no Postgres, NULL nunca conflita com NULL numa chave única. A
-- regra de fracionamento grava `operacao_id` nulo (é do tomador, não de uma
-- operação), então a constraint ingênua deixava passar uma duplicata por
-- varredura. Comprovado em teste antes desta correção existir.
create unique index if not exists ocorrencia_unica on ocorrencia_atipicidade (
    regra,
    coalesce(tomador_id, '00000000-0000-0000-0000-000000000000'::uuid),
    coalesce(operacao_id, '00000000-0000-0000-0000-000000000000'::uuid),
    detalhe
);

-- Append-only, exceto o par de campos do adaptador: uma trilha de
-- atipicidade que pode ser editada não serve como defesa.
create or replace function fn_ocorrencia_append_only()
returns trigger as $$
begin
    if tg_op = 'DELETE' then
        raise exception 'Ocorrência de atipicidade não pode ser apagada.'
            using errcode = 'OC014';
    end if;

    if new.regra is distinct from old.regra
       or new.severidade is distinct from old.severidade
       or new.tomador_id is distinct from old.tomador_id
       or new.operacao_id is distinct from old.operacao_id
       or new.detalhe is distinct from old.detalhe
       or new.created_at is distinct from old.created_at then
        raise exception
            'Ocorrência de atipicidade é imutável: só o registro da comunicação pode ser preenchido.'
            using errcode = 'OC014';
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_ocorrencia_append_only on ocorrencia_atipicidade;
create trigger trg_ocorrencia_append_only
    before update or delete on ocorrencia_atipicidade
    for each row execute function fn_ocorrencia_append_only();

-- Varredura sobre os dados que JÁ existem. Nenhuma destas regras depende
-- de integração externa — é por isso que são construíveis hoje.
--
-- `p_limiar` é parâmetro de negócio: o valor de referência de atenção
-- fiscal muda, e a regra não deve mudar junto.
create or replace function fn_detectar_atipicidades(
    p_limiar        numeric default 10000,
    p_janela_dias   int default 30
) returns int as $$
declare
    v_total  int := 0;
    -- GET DIAGNOSTICS só ATRIBUI: `get diagnostics v_total = v_total +
    -- row_count` é erro de sintaxe. Daí a variável auxiliar por regra.
    v_linhas int;
begin
    -- REGRA 1 — Fracionamento (smurfing): várias operações pequenas do
    -- mesmo tomador numa janela curta, somando acima do limiar. É o padrão
    -- clássico de quem quer ficar abaixo do radar de cada operação isolada.
    with fracionadas as (
        select oc.tomador_id,
               count(*) as qtd,
               sum(oc.valor_principal) as soma
        from operacao_credito oc
        where oc.created_at >= current_date - make_interval(days => p_janela_dias)
          and oc.valor_principal < p_limiar
          and oc.status <> 'cancelada'
        group by oc.tomador_id
        having count(*) >= 3 and sum(oc.valor_principal) >= p_limiar
    )
    insert into ocorrencia_atipicidade (regra, severidade, tomador_id, detalhe)
    select 'fracionamento', 'alta', f.tomador_id,
           format('%s operações abaixo de %s em %s dias, somando %s',
                  f.qtd, p_limiar, p_janela_dias, f.soma)
    from fracionadas f
    on conflict (
        regra,
        coalesce(tomador_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(operacao_id, '00000000-0000-0000-0000-000000000000'::uuid),
        detalhe
    ) do nothing;
    get diagnostics v_linhas = row_count;
    v_total := v_total + v_linhas;

    -- REGRA 2 — Liquidação muito antecipada. Tomar crédito e devolver quase
    -- imediatamente não é ilegal, mas é o formato de quem usa a operação
    -- para dar aparência lícita a recurso já disponível.
    with antecipadas as (
        select oc.id, oc.tomador_id,
               (select min(p.vencimento) from parcela p where p.operacao_id = oc.id) as primeiro_venc
        from operacao_credito oc
        where oc.status = 'liquidada'
    )
    insert into ocorrencia_atipicidade (regra, severidade, tomador_id, operacao_id, detalhe)
    select 'liquidacao_antecipada', 'media', a.tomador_id, a.id,
           format('Liquidada antes do primeiro vencimento (%s)', a.primeiro_venc)
    from antecipadas a
    where a.primeiro_venc is not null and a.primeiro_venc > current_date
    on conflict (
        regra,
        coalesce(tomador_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(operacao_id, '00000000-0000-0000-0000-000000000000'::uuid),
        detalhe
    ) do nothing;
    get diagnostics v_linhas = row_count;
    v_total := v_total + v_linhas;

    -- REGRA 3 — Pagamento em excesso relevante. Um crédito muito acima do
    -- devido pode ser mora legítima; acima de 10% E de R$ 1.000 já merece
    -- um par de olhos, porque é o formato de injeção de recurso disfarçada
    -- de pagamento.
    insert into ocorrencia_atipicidade (regra, severidade, tomador_id, operacao_id, detalhe)
    select 'pagamento_em_excesso', 'baixa', oc.tomador_id, oc.id,
           format('Movimento %s para parcela %s de %s', m.documento, p.numero, p.valor_total)
    from parcela p
    join movimento_bancario m on m.id = p.movimento_id
    join operacao_credito oc on oc.id = p.operacao_id
    where m.valor - p.valor_total > 1000
      and m.valor > p.valor_total * 1.10
    on conflict (
        regra,
        coalesce(tomador_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(operacao_id, '00000000-0000-0000-0000-000000000000'::uuid),
        detalhe
    ) do nothing;
    get diagnostics v_linhas = row_count;
    v_total := v_total + v_linhas;

    return v_total;
end;
$$ language plpgsql;
