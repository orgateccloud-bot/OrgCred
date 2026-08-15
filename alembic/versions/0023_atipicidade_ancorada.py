"""023 - a REGRA 2 de `fn_detectar_atipicidades` passa a comparar o primeiro
vencimento com a DATA DO ENCERRAMENTO (lida de operacao_evento, 008) em vez de
com current_date, e o write-off precoce ganha regra própria
(`baixa_prejuizo_antecipada`).

Baseline convertido de migrations/023_atipicidade_ancorada.sql.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-15
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Só redefine uma função. Nenhuma linha de `ocorrencia_atipicidade` é
    tocada — nem poderia ser, porque a tabela é append-only (OC014) e o
    TRUNCATE é recusado desde a 016.

    O EFEITO NA PRIMEIRA VARREDURA DEPOIS DESTE UPGRADE É UM PICO DE
    OCORRÊNCIAS, e ele é esperado. A regra da 010 só enxergava a operação
    enquanto o primeiro vencimento dela estivesse no futuro; toda operação
    liquidada antes do primeiro vencimento cuja varredura só rodou depois
    daquela data passou em branco e continuou passando. Elas voltam agora,
    todas de uma vez, porque a correção é retroativa sobre a base inteira. O
    número não mede uma mudança de comportamento dos tomadores: mede o que a
    janela de validade da 010 vinha descartando em silêncio.

    Para dimensionar o pico ANTES de rodar a varredura (a consulta abaixo não
    escreve nada e reproduz o filtro novo):

        select oc.status, count(*)
          from operacao_credito oc
         where oc.status in ('liquidada', 'baixada_prejuizo')
           and (select min(p.vencimento) from parcela p
                 where p.operacao_id = oc.id) is not null
           and coalesce(
                 (select min(e.created_at)::date from operacao_evento e
                   where e.operacao_id = oc.id and e.status_novo = oc.status),
                 '-infinity'::date)
               < (select min(p.vencimento) from parcela p
                   where p.operacao_id = oc.id)
           and not exists (
                 select 1 from ocorrencia_atipicidade o
                  where o.operacao_id = oc.id
                    and o.regra in ('liquidacao_antecipada',
                                    'baixa_prejuizo_antecipada'))
         group by oc.status;

    NÃO HÁ DUPLICAÇÃO DO HISTÓRICO, embora o texto do `detalhe` mude. O
    detalhe entra no índice `ocorrencia_unica` (010), então mudar o texto
    reinseriria cada ocorrência já gravada sob a redação antiga — e, sendo a
    tabela append-only, a duplicata seria permanente. A 023 corta isso na
    origem: a REGRA 2 passa a se guardar por (regra, operacao_id) com um `not
    exists` explícito, que é a chave natural do fato. Ocorrência antiga fica
    com o texto da época, como convém a uma trilha; operação nova nasce com as
    duas datas no detalhe.
    """
    sql = (_SQL_DIR / "023_atipicidade_ancorada.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Reaplica a definição da 010 e, com ela, o defeito.

    Descer daqui devolve `fn_detectar_atipicidades` à versão cuja REGRA 2
    compara `primeiro_venc` com `current_date`: a detecção volta a valer
    apenas enquanto o primeiro vencimento estiver no futuro e a desaparecer
    para sempre no dia seguinte, embora o fato detectado seja imutável. Como a
    varredura só roda por clique manual, isso é, na prática, desligar a regra.
    O write-off precoce (`baixa_prejuizo_antecipada`) deixa de ser detectado
    por completo.

    A DEFINIÇÃO ANTIGA É REESCRITA AQUI, e o arquivo da 010 NÃO é reexecutado
    — mesma razão do downgrade da 022: reexecutá-lo recriaria de quebra a
    `v_tomadores_sem_identificacao` sem 'baixada_prejuizo' no capital exposto
    (correção da 017), e um downgrade que apaga a correção de outra migration
    é regressão, não downgrade. O único objeto que a 023 alterou foi
    `fn_detectar_atipicidades`, e é só ele que volta.

    AS OCORRÊNCIAS JÁ GRAVADAS FICAM. Não há como removê-las (OC014) e não
    haveria por quê: elas descrevem fatos verdadeiros. O que muda é que as
    linhas de `baixa_prejuizo_antecipada` passam a ser órfãs de regra — ficam
    na tela sem que nada volte a produzi-las.
    """
    op.execute("""
        create or replace function fn_detectar_atipicidades(
            p_limiar        numeric default 10000,
            p_janela_dias   int default 30
        ) returns int as $$
        declare
            v_total  int := 0;
            v_linhas int;
        begin
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
    """)
    op.execute("comment on function fn_detectar_atipicidades(numeric, int) is null")
