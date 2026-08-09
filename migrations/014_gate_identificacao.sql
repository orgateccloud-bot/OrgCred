-- OrgCred — ativar exige identificação do tomador com evidência arquivada
--
-- A migration 010 construiu a identificação com evidência (hash SHA-256
-- verificável, retenção de 5 anos) e deixou a amarra DESLIGADA, expondo a
-- lacuna em `v_tomadores_sem_identificacao` para a decisão ser tomada com o
-- número na mão. A decisão foi tomada: liga.
--
-- O QUE MUDA: comprometer capital com um tomador sem NENHUMA evidência de
-- identificação arquivada passa a ser recusado. Emprestar para quem não se
-- sabe quem é não é falha de processo — é o cenário que a Lei 9.613/98
-- (art. 10, I) existe para impedir.
--
-- REGRA MÍNIMA DEFENSÁVEL: pelo menos UM documento arquivado. Exigir um tipo
-- específico (contrato social, documento dos sócios) é decisão de negócio
-- que muda conforme a política de KYC da ESC, e seria arbitrário eu escolher
-- qual. `tomador_documento.tipo` já existe para quando essa política for
-- definida; a checagem aqui é a base sobre a qual ela se apoia.
--
-- Documento expurgado depois do prazo de retenção deixa de contar, e é
-- correto: se a evidência não existe mais, não há o que apresentar numa
-- fiscalização.
--
-- MESMA DISCIPLINA DA MIGRATION 013 (gate de registro):
-- - Não é retroativo. Operações já ativas seguem ativas — o trigger roda na
--   transição, e revogar o que já foi emprestado não devolveria o dinheiro.
-- - Reativar inadimplente NÃO revalida: é ato sobre operação que já
--   comprometia capital.
--
-- Novo SQLSTATE OC019 — código próprio, e não OC004, porque é outra regra e
-- outra lei: OC004 é registro em entidade registradora (LC 167/2019,
-- art. 5º §3º); este é identificação do cliente (Lei 9.613/98, art. 10, I).
-- Compartilhar código faria a UI dar a instrução errada ao operador.
--
-- Redefine fn_check_teto_capital inteira (PL/pgSQL não tem substituição
-- parcial). O único bloco novo em relação à 013 é o da identificação.

create or replace function fn_check_teto_capital()
returns trigger as $$
declare
    v_capital_atual         numeric(14,2);
    v_comprometido_outras   numeric(14,2);
    v_disponivel            numeric(14,2);
    v_municipio_ok          boolean;
    v_usuario_id            text;
    v_comprometia_antes     boolean;
    v_compromete_agora      boolean;
begin
    v_usuario_id := nullif(current_setting('app.user_id', true), '');

    -- Fonte única da verdade sobre o que ocupa o teto. 'inadimplente' entra
    -- aqui: o título saiu de 'ativa', mas o dinheiro continua fora.
    v_comprometia_antes := tg_op = 'UPDATE' and old.status in ('ativa','inadimplente');
    v_compromete_agora  := new.status in ('ativa','inadimplente');

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

        -- Renegociar só dentro de fn_novar_operacao, que faz a baixa e a
        -- criação da substituta na MESMA transação e sob o mesmo lock. Fora
        -- dela, a original sairia do comprometido sem substituta amarrada —
        -- e nada impediria criar a substituta depois, contando o capital
        -- duas vezes em janelas diferentes.
        if new.status = 'renegociada'
           and coalesce(current_setting('app.novacao_em_curso', true), '') <> '1' then
            raise exception
                'Renegociação exige novação atômica: use fn_novar_operacao (operação %).',
                new.id
                using errcode = 'OC008';
        end if;
    end if;

    if tg_op = 'INSERT' and new.status not in ('proposta','registrada') then
        raise exception
            'Operação não pode ser criada já no status % (operação %).',
            new.status, new.id
            using errcode = 'OC003';
    end if;

    -- Substituta de novação também só nasce dentro da função atômica.
    if tg_op = 'INSERT' and new.substitui_operacao_id is not null
       and coalesce(current_setting('app.novacao_em_curso', true), '') <> '1' then
        raise exception
            'Operação substituta só pode ser criada por fn_novar_operacao (operação %).',
            new.id
            using errcode = 'OC008';
    end if;

    -- ENTRADA no comprometido: só quando a operação passa a ocupar o teto
    -- vindo de um estado que NÃO ocupava.
    if v_compromete_agora and (tg_op = 'INSERT' or not v_comprometia_antes) then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        -- Registro em entidade registradora (migration 013).
        if not exists (
            select 1 from registro_operacao r
            where r.operacao_id = new.id and r.status = 'confirmado'
        ) then
            raise exception
                'Ativação bloqueada: operação % sem registro CONFIRMADO em entidade registradora (Art. 5º §3º, LC 167/2019).',
                new.id
                using errcode = 'OC004';
        end if;

        -- BLOCO NOVO NESTA MIGRATION.
        -- Identificação do tomador com evidência arquivada. Vem ANTES do
        -- gate geográfico de propósito: não saber quem é o tomador é falha
        -- mais grave do que ele estar fora da área, e a mensagem mais útil
        -- é a da falha mais grave.
        if not exists (
            select 1 from tomador_documento d where d.tomador_id = new.tomador_id
        ) then
            raise exception
                'Ativação bloqueada: tomador % sem evidência de identificação arquivada (Lei 9.613/98, art. 10, I). Operação %.',
                new.tomador_id, new.id
                using errcode = 'OC019';
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

        select coalesce(sum(valor_principal), 0) into v_comprometido_outras
        from operacao_credito
        where status in ('ativa','inadimplente') and id <> new.id;

        v_disponivel := v_capital_atual - v_comprometido_outras;

        if new.valor_principal > v_disponivel then
            raise exception
                'Teto de capital excedido (Art. 5º, LC 167/2019). Capital disponível: %, valor solicitado: %. Operação % bloqueada.',
                v_disponivel, new.valor_principal, new.id
                using errcode = 'OC001';
        end if;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values ('ativacao_operacao', new.valor_principal, new.id, v_disponivel - new.valor_principal, v_usuario_id);
    end if;

    -- SAÍDA do comprometido: qualquer transição que deixa de ocupar o teto
    -- vindo de um estado que ocupava. Cobre liquidada E renegociada, e
    -- também a partir de 'inadimplente'.
    --
    -- ativa -> inadimplente NÃO cai aqui de propósito: os dois estados
    -- comprometem, então não há movimento de capital para registrar.
    if tg_op = 'UPDATE' and v_comprometia_antes and not v_compromete_agora then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual into v_capital_atual from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido_outras
        from operacao_credito
        where status in ('ativa','inadimplente') and id <> new.id;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values (
            case when new.status = 'renegociada' then 'renegociacao' else 'liquidacao' end,
            new.valor_principal, new.id,
            v_capital_atual - v_comprometido_outras, v_usuario_id
        );
    end if;

    new.updated_at := now();
    return new;
end;
$$ language plpgsql;
