-- OrgCred — o vigente não se fabrica por salto de versão
--
-- Um ataque reproduzido contra o banco de dev, por SQL direto:
--
--   insert into contrato_emprestimo (operacao_id, versao, corpo, sha256)
--     values (<op>, 99, 'CONTRATO FORJADO: dívida perdoada', ...);
--   insert into apuracao_fiscal (ano, trimestre, versao, receita_juros, ...)
--     values (2026, 1, 99, 888888, ..., total_tributos = 0);
--
-- As duas viravam a linha VIGENTE — `v_contrato_vigente` e `v_apuracao_vigente`
-- servem a MAIOR versão —, com a imutabilidade da 016/017/018 intacta: aquela
-- guarda o UPDATE e o DELETE, e o INSERT nunca teve dono. O `trg_contrato_hash`
-- (012) recalcula o sha do corpo que você mandar, então o hash SEMPRE confere —
-- ele assina o forjado com a mesma tinta do legítimo.
--
-- É a mesma classe do apêndice de parcela que a 027 fechou (INSERT numa tabela
-- que a imutabilidade só protegia contra UPDATE/DELETE).
--
-- ---------------------------------------------------------------------
-- O QUE ESTA MIGRATION FECHA, E POR QUE NÃO VAI ALÉM
-- ---------------------------------------------------------------------
-- MONOTONIA DE VERSÃO, nas duas tabelas: toda inserção tem que ser a PRÓXIMA
-- versão (max+1). O vigente é a maior versão, então o salto para 99 era o que
-- fabricava um vigente do nada — e é exatamente o que a monotonia mata. O
-- caminho legítimo não sente: contrato insere `coalesce(max(versao),0)+1`
-- (contratos.py) e `fn_apurar_trimestre` idem. É condição sobre o DADO, na
-- disciplina do resto do motor.
--
-- O QUE NÃO É FECHADO AQUI, DE PROPÓSITO — e escrito para não virar surpresa:
--
--   (a) UMA FORJA NA PRÓXIMA VERSÃO ainda é possível por SQL direto (versão
--       exata max+1, corpo/números inventados). Isso é o resíduo do §7: a role
--       da aplicação é dona das tabelas, e nenhum trigger sobrevive a quem pode
--       `alter table ... disable trigger`. A monotonia estreita o ataque de
--       "qualquer versão alta" para "exatamente a próxima", e torna a série sem
--       buracos — uma versão que a trilha de eventos (008/010) não criou fica
--       visível.
--
--   (b) UMA APURAÇÃO COM NÚMEROS QUE NÃO FECHAM já é DENUNCIADA, e por um
--       mecanismo que existe justamente para isto: a memória de cálculo
--       (app/routers/fiscal.py) recomputa a apuração pela fórmula vigente e
--       devolve `confere=false` com as divergências. Uma tentativa anterior
--       desta migration ENCODOU a fórmula num CHECK para RECUSAR a linha torta
--       no INSERT — e um teste a derrubou com razão: a memória existe porque a
--       fórmula EVOLUI (a 018 mudou a 011), e uma apuração gravada sob a fórmula
--       antiga passa a divergir da nova de propósito. Um CHECK amarrado à
--       fórmula recusaria essas linhas históricas e transformaria toda evolução
--       futura de fórmula num migration que revalida o passado. Prevenir a
--       forja aqui custaria quebrar o recurso que a detecta. A escolha é
--       detectar (memória) e nomear o resíduo (§7), não acoplar o banco à
--       fórmula.
create or replace function fn_contrato_versao_sequencial()
returns trigger as $$
declare
    v_prox int;
begin
    select coalesce(max(versao), 0) + 1 into v_prox
      from contrato_emprestimo where operacao_id = new.operacao_id;
    if new.versao <> v_prox then
        raise exception
            'Contrato da operação % só aceita a versão % (recebida: %): o instrumento vigente não se fabrica por versão avulsa; reemita pelo fluxo.',
            new.operacao_id, v_prox, new.versao
            using errcode = 'OC017';
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_contrato_versao_sequencial on contrato_emprestimo;
create trigger trg_contrato_versao_sequencial
    before insert on contrato_emprestimo
    for each row execute function fn_contrato_versao_sequencial();

create or replace function fn_apuracao_versao_sequencial()
returns trigger as $$
declare
    v_prox int;
begin
    select coalesce(max(versao), 0) + 1 into v_prox
      from apuracao_fiscal where ano = new.ano and trimestre = new.trimestre;
    if new.versao <> v_prox then
        raise exception
            'Apuração de %/T% só aceita a versão % (recebida: %): a apuração vigente não se fabrica por versão avulsa; retifique pelo fluxo.',
            new.ano, new.trimestre, v_prox, new.versao
            using errcode = 'OC016';
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_apuracao_versao_sequencial on apuracao_fiscal;
create trigger trg_apuracao_versao_sequencial
    before insert on apuracao_fiscal
    for each row execute function fn_apuracao_versao_sequencial();

comment on function fn_contrato_versao_sequencial() is
    'OC017 — a versão de contrato inserida tem que ser a próxima (max+1). Mata o salto de versão que forjava o instrumento vigente. Corpo continua sendo gerado pela app e não re-derivável pelo banco: ver o §7.';
comment on function fn_apuracao_versao_sequencial() is
    'OC016 — a versão de apuração inserida tem que ser a próxima (max+1). Números inconsistentes já são denunciados pela memória de cálculo; acoplar a fórmula a um CHECK quebraria a evolução de fórmula que a memória existe para cobrir.';
