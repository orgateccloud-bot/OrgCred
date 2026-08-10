-- OrgCred — apuração fiscal da receita da ESC (Lucro Presumido)
--
-- ESCOPO: a receita da própria ESC, não o IOF. O IOF-crédito segue
-- bloqueado em parecer jurídico-tributário (ver app/routers/fiscal.py) e
-- nada aqui o antecipa.
--
-- REGIME: Lucro Presumido, por decisão do dono do negócio. Uma ESC não pode
-- optar pelo Simples Nacional (vedação legal), então a escolha real era
-- Presumido ou Real — e o Presumido apura TRIMESTRALMENTE, o que define o
-- período desta apuração.
--
-- NENHUMA ALÍQUOTA VEM SEMEADA, DE PROPÓSITO. Percentuais de presunção,
-- alíquotas e o limite do adicional de IRPJ são matéria tributária: se
-- viessem embutidas no código, seriam um número escolhido por quem escreveu
-- o sistema, não pelo contador. Sem parâmetro vigente, a apuração é
-- recusada (OC015) em vez de produzir um valor plausível e errado.
--
-- A RECEITA É SÓ O JURO. A amortização é devolução de principal — dinheiro
-- que sai e volta, não resultado. Somar amortização na base inflaria a
-- tributação em várias vezes.
--
-- Novos SQLSTATEs:
--   OC015 = apuração sem parâmetro fiscal vigente
--   OC016 = apuração fiscal é imutável (retificação cria nova versão)

-- ---------------------------------------------------------------------
-- Parâmetros, com vigência
-- ---------------------------------------------------------------------
-- Vigência, e não um registro único editável: alíquota muda por lei, e uma
-- apuração de 2026 tem que continuar reproduzível com os números de 2026.
create table if not exists parametro_fiscal (
    id                          uuid primary key default uuid_generate_v4(),
    vigencia_inicio             date not null,
    percentual_presuncao_irpj   numeric(6,4) not null,
    percentual_presuncao_csll   numeric(6,4) not null,
    aliquota_irpj               numeric(6,4) not null,
    aliquota_csll               numeric(6,4) not null,
    adicional_irpj_aliquota     numeric(6,4) not null,
    adicional_irpj_limite       numeric(14,2) not null,
    aliquota_pis                numeric(6,4) not null,
    aliquota_cofins             numeric(6,4) not null,
    -- Caixa ou competência muda materialmente o número, e a opção é do
    -- contador — não de quem escreve o sistema.
    regime_reconhecimento       text not null,
    observacao                  text,
    usuario_id                  text,
    created_at                  timestamp not null default clock_timestamp(),
    constraint parametro_regime_valido check (regime_reconhecimento in ('caixa', 'competencia')),
    constraint parametro_percentuais_validos check (
        percentual_presuncao_irpj between 0 and 1
        and percentual_presuncao_csll between 0 and 1
        and aliquota_irpj between 0 and 1
        and aliquota_csll between 0 and 1
        and adicional_irpj_aliquota between 0 and 1
        and aliquota_pis between 0 and 1
        and aliquota_cofins between 0 and 1
    ),
    constraint parametro_limite_nao_negativo check (adicional_irpj_limite >= 0),
    constraint parametro_vigencia_unica unique (vigencia_inicio)
);

create or replace view v_parametro_fiscal_vigente as
select * from parametro_fiscal
where vigencia_inicio <= current_date
order by vigencia_inicio desc
limit 1;

-- ---------------------------------------------------------------------
-- Apuração trimestral
-- ---------------------------------------------------------------------
-- Os parâmetros usados são COPIADOS para dentro da apuração. Guardar só a
-- FK para parametro_fiscal faria a apuração mudar de valor se a linha de
-- parâmetro fosse editada depois — e um número fiscal que muda sozinho não
-- se defende em lugar nenhum.
--
-- `versao`: retificação existe no mundo real (DCTF retificadora). Em vez de
-- editar a apuração original — o que apagaria o que foi declarado —, uma
-- nova versão é gravada e a anterior permanece.
create table if not exists apuracao_fiscal (
    id                          uuid primary key default uuid_generate_v4(),
    ano                         int not null,
    trimestre                   int not null,
    versao                      int not null default 1,
    receita_juros               numeric(14,2) not null,
    base_irpj                   numeric(14,2) not null,
    irpj                        numeric(14,2) not null,
    adicional_irpj              numeric(14,2) not null,
    base_csll                   numeric(14,2) not null,
    csll                        numeric(14,2) not null,
    pis                         numeric(14,2) not null,
    cofins                      numeric(14,2) not null,
    total_tributos              numeric(14,2) not null,
    -- Snapshot dos parâmetros aplicados.
    percentual_presuncao_irpj   numeric(6,4) not null,
    percentual_presuncao_csll   numeric(6,4) not null,
    aliquota_irpj               numeric(6,4) not null,
    aliquota_csll               numeric(6,4) not null,
    adicional_irpj_aliquota     numeric(6,4) not null,
    adicional_irpj_limite       numeric(14,2) not null,
    aliquota_pis                numeric(6,4) not null,
    aliquota_cofins             numeric(6,4) not null,
    regime_reconhecimento       text not null,
    usuario_id                  text,
    created_at                  timestamp not null default clock_timestamp(),
    constraint apuracao_trimestre_valido check (trimestre between 1 and 4),
    constraint apuracao_versao_unica unique (ano, trimestre, versao)
);

create index if not exists idx_apuracao_periodo on apuracao_fiscal(ano desc, trimestre desc);

create or replace function fn_apuracao_imutavel()
returns trigger as $$
begin
    raise exception
        'Apuração fiscal é imutável: retificação grava uma nova versão do trimestre.'
        using errcode = 'OC016';
end;
$$ language plpgsql;

drop trigger if exists trg_apuracao_imutavel on apuracao_fiscal;
create trigger trg_apuracao_imutavel
    before update or delete on apuracao_fiscal
    for each row execute function fn_apuracao_imutavel();

-- Última versão de cada trimestre — é o que a tela mostra.
create or replace view v_apuracao_vigente as
select distinct on (ano, trimestre) *
from apuracao_fiscal
order by ano desc, trimestre desc, versao desc;

-- ---------------------------------------------------------------------
-- Cálculo
-- ---------------------------------------------------------------------
create or replace function fn_apurar_trimestre(
    p_ano       int,
    p_trimestre int,
    p_usuario   text default null
) returns uuid as $$
declare
    v_par       parametro_fiscal%rowtype;
    v_inicio    date;
    v_fim       date;
    v_receita   numeric(14,2);
    v_base_irpj numeric(14,2);
    v_base_csll numeric(14,2);
    v_irpj      numeric(14,2);
    v_adicional numeric(14,2);
    v_csll      numeric(14,2);
    v_pis       numeric(14,2);
    v_cofins    numeric(14,2);
    v_versao    int;
    v_id        uuid;
begin
    if p_trimestre not between 1 and 4 then
        raise exception 'Trimestre inválido: %.', p_trimestre using errcode = 'OC015';
    end if;

    select * into v_par from v_parametro_fiscal_vigente;
    if not found then
        raise exception
            'Não há parâmetro fiscal vigente: configure presunção e alíquotas antes de apurar.'
            using errcode = 'OC015';
    end if;

    v_inicio := make_date(p_ano, (p_trimestre - 1) * 3 + 1, 1);
    v_fim    := (v_inicio + interval '3 months')::date;

    -- Só o JURO. A amortização devolve principal e não é resultado.
    if v_par.regime_reconhecimento = 'caixa' then
        select coalesce(sum(valor_juros), 0) into v_receita
        from parcela
        where status = 'paga' and pago_em >= v_inicio and pago_em < v_fim;
    else
        select coalesce(sum(valor_juros), 0) into v_receita
        from parcela
        where vencimento >= v_inicio and vencimento < v_fim;
    end if;

    v_base_irpj := round(v_receita * v_par.percentual_presuncao_irpj, 2);
    v_base_csll := round(v_receita * v_par.percentual_presuncao_csll, 2);

    v_irpj      := round(v_base_irpj * v_par.aliquota_irpj, 2);
    -- Adicional incide só sobre o que excede o limite do TRIMESTRE.
    v_adicional := round(
        greatest(v_base_irpj - v_par.adicional_irpj_limite, 0) * v_par.adicional_irpj_aliquota, 2
    );
    v_csll      := round(v_base_csll * v_par.aliquota_csll, 2);
    -- PIS/COFINS cumulativos incidem sobre a RECEITA, não sobre a base
    -- presumida — presunção é conceito de IRPJ/CSLL.
    v_pis       := round(v_receita * v_par.aliquota_pis, 2);
    v_cofins    := round(v_receita * v_par.aliquota_cofins, 2);

    select coalesce(max(versao), 0) + 1 into v_versao
    from apuracao_fiscal where ano = p_ano and trimestre = p_trimestre;

    insert into apuracao_fiscal (
        ano, trimestre, versao, receita_juros,
        base_irpj, irpj, adicional_irpj, base_csll, csll, pis, cofins, total_tributos,
        percentual_presuncao_irpj, percentual_presuncao_csll,
        aliquota_irpj, aliquota_csll, adicional_irpj_aliquota, adicional_irpj_limite,
        aliquota_pis, aliquota_cofins, regime_reconhecimento, usuario_id
    ) values (
        p_ano, p_trimestre, v_versao, v_receita,
        v_base_irpj, v_irpj, v_adicional, v_base_csll, v_csll, v_pis, v_cofins,
        v_irpj + v_adicional + v_csll + v_pis + v_cofins,
        v_par.percentual_presuncao_irpj, v_par.percentual_presuncao_csll,
        v_par.aliquota_irpj, v_par.aliquota_csll,
        v_par.adicional_irpj_aliquota, v_par.adicional_irpj_limite,
        v_par.aliquota_pis, v_par.aliquota_cofins, v_par.regime_reconhecimento, p_usuario
    ) returning id into v_id;

    return v_id;
end;
$$ language plpgsql;
