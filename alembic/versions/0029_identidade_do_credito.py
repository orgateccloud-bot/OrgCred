"""029 - a identidade de um crédito é (documento, valor, data_movimento): a
conta sai da chave e vira proveniência; e OC026 ganha o lock que faltava.

Fecha a CLASSE inteira que derrubou a 027 e a 028. As duas tentaram pôr a conta
na identidade — uma pela grafia, outra pela grafia canonizada — e as duas
duplicaram lastro, porque uma exportação sempre pode declarar MENOS que outra
sobre a mesma conta. Canonização normaliza formato; não recupera informação
ausente.

Baseline convertido de migrations/029_identidade_do_credito.sql.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-27
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Uma restrição única nova, uma view e uma função recriada com lock.

    PODE FALHAR EM BASE COM DADOS, e a diferença em relação à 028 importa: lá o
    modo de falha era uma armadilha, aqui é o sinal correto.

    A restrição nova, `(documento, valor, data_movimento)`, é ORTOGONAL à da
    028 — nenhuma implica a outra. Ela aborta se a base já tem o MESMO crédito
    gravado duas vezes, e uma base assim só existe se ela caiu no crítico da 027
    ou no da 028. Conferir antes:

        select documento, valor, data_movimento,
               count(*), array_agg(id), array_agg(conta_origem),
               array_agg(arquivo_sha256)
          from movimento_bancario
         group by 1, 2, 3
        having count(*) > 1;

    Cada grupo é um crédito contado mais de uma vez. E aqui está a diferença
    para a 028: as linhas duplicadas são, por construção, IGUAIS no que importa
    (mesmo identificador, mesmo valor, mesma data) — variam só na grafia da
    conta e no sha256 do arquivo que as trouxe. Escolher qual fica não exige
    conciliação de negócio; exige saber qual delas já lastreou uma baixa:

        select m.id, m.documento, m.conta_origem, p.id as parcela_id, p.status
          from movimento_bancario m
          left join parcela p on p.movimento_id = m.id
         where (m.documento, m.valor, m.data_movimento) in (
                 select documento, valor, data_movimento
                   from movimento_bancario
                  group by 1, 2, 3 having count(*) > 1);

    A que NÃO lastreia nada é a excedente. Removê-la exige desligar
    `trg_movimento_imutavel` (OC012) — a tabela recusa DELETE por decisão —, e
    isso é ato de operador com registro, não de migration: apagar lastro
    bancário é destruir prova, e a migration não pode decidir qual prova morre.

    PRODUÇÃO NÃO PRECISA DISSO. Ela roda o schema 0026 e tem `movimento_bancario`
    vazio (medido); as três migrations sobem de uma vez, em base limpa.

    O QUE ESPERAR DEPOIS DE SUBIR:

      1. o mesmo crédito deixa de entrar duas vezes, tenha vindo por qual grafia
         de conta for — inclusive na fronteira entre o lançamento MANUAL e o
         OFX, que até aqui eram espaços de nomes distintos;

      2. dois bancos que emitam o mesmo FITID com o mesmo valor no mesmo dia
         passam a colidir, e a segunda linha é pulada. É o custo assumido no
         cabeçalho do .sql, e ele aparece no relatório de importação como
         `conflitos` — não como `ja_registrados`;

      3. a baixa passa a segurar a operação com `for share` até o commit. Uma
         renegociação concorrente espera, em vez de atravessar o gate OC026.
    """
    sql = (_SQL_DIR / "029_identidade_do_credito.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Remove a chave do crédito, a view, e devolve `fn_operacao_em_cobranca`
    à forma sem lock da 028.

    NÃO É DESTRUTIVO E NÃO PODE FALHAR POR DADO — remover restrição não valida
    nada, e a função é recriada por `create or replace`.

    REABRE A CLASSE INTEIRA: descer daqui devolve a duplicação de lastro por
    grafia de conta (as duas metades, BANKID e ACCTID), a fronteira aberta entre
    manual e OFX, e o gate OC026 que uma transição concorrente atravessa. Como
    o efeito de cada uma dessas é capital voltando ao teto do Art. 5º contra
    dinheiro que não entrou, descer daqui em base com movimento gravado só faz
    sentido para investigar — nunca para operar.
    """
    op.execute("""
        alter table movimento_bancario
            drop constraint if exists movimento_credito_unico
    """)
    op.execute("drop view if exists v_credito_por_identidade")
    op.execute("""
        create or replace function fn_operacao_em_cobranca(p_operacao_id uuid)
        returns text as $$
        declare
            v_status text;
        begin
            select status into v_status from operacao_credito where id = p_operacao_id;
            if not found then
                return 'inexistente';
            end if;
            return v_status;
        end;
        $$ language plpgsql stable;
    """)
