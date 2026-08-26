"""027 - as bordas da cobrança, segunda volta: o FITID passa a ser único por
CONTA (e não no universo), o INSERT em `parcela` ganha guarda (OC025) e a
cobertura de valor da baixa sai de dentro de `fn_baixar_parcela` para o
trigger, alcançável por qualquer porta (OC011).

Fecha os três furos que a 016 não olhou por estarem fora do caminho dela: um
crédito real descartado como "já registrado" quando dois bancos emitem o mesmo
FITID, uma décima terceira parcela acrescentada por INSERT a um contrato de
doze, e uma carteira inteira quitada contra tarifas de um centavo.

Baseline convertido de migrations/027_bordas_da_cobranca_2.sql.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-26
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Uma troca de chave única, um trigger novo e uma função recriada.
    Nenhuma linha é reescrita e não há back-fill.

    O UPGRADE É SEGURO EM BASE COM DADOS, e a razão é estrutural em vez de
    empírica — vale conferir antes de rodar, porque é diferente do aviso da
    016 e da 024:

      - a chave nova de `movimento_bancario` é ESTRITAMENTE MAIS FRACA que a
        que ela substitui. `unique (documento)` implica `unique (documento,
        conta_origem)`, então nenhuma linha existente pode violar a nova e o
        `ADD CONSTRAINT` não tem como falhar com 23505. É o oposto do risco
        habitual de constraint nova, que é ficar restritiva demais para o dado
        já gravado;

      - a guarda de INSERT em `parcela` só age sobre INSERTs FUTUROS. Ela não
        valida nada do que está na tabela, e a agenda já emitida — que por
        construção tem exatamente `numero_parcelas` linhas por operação ativa —
        não é revisitada;

      - `create or replace function` troca o corpo sem tocar em linha nenhuma.

    O QUE ESPERAR DEPOIS DE SUBIR, para ninguém tratar como incidente:

      1. passa a ser POSSÍVEL existir dois movimentos com o mesmo `documento`,
         desde que de `conta_origem` diferentes. É o conserto, não uma
         regressão: FITID é único dentro da conta do banco, e a chave global
         fazia o segundo banco ser silenciosamente descartado como "já
         registrado" — com a aritmética do relatório de importação fechando,
         que é o que tornava o defeito invisível. A tela de movimentos já
         mostra `conta_origem` desde a 024 e é ela que distingue as duas
         linhas;

      2. `insert into parcela` passa a ser recusado com OC025 em toda situação
         que não seja a emissão da agenda pela ativação. Nenhum endpoint faz
         isso (a agenda é escrita só por `fn_gerar_parcelas`, de dentro do
         trigger da 007), então nada da aplicação muda de comportamento —
         mas um script de correção que acrescentava parcela à mão deixa de
         funcionar, e é para isso que a guarda existe;

      3. `update parcela set status='paga', movimento_id=X` por SQL direto
         passa a exigir que X CUBRA a parcela, com o mesmo OC011 que
         `fn_baixar_parcela` já devolvia. A validação deixa de morar só na
         função e passa a valer por qualquer porta;

      4. `truncate parcela` passa a ser recusado com OC009 — e, por tabela,
         `truncate movimento_bancario cascade` junto, porque a FK arrasta
         `parcela` para o mesmo comando. É o que sustenta o item 2: sem isso, a
         guarda de INSERT tinha uma porta de dois comandos (esvaziar a tabela
         deixa a operação 'ativa' com a agenda "incompleta", e o apêndice entra
         sem recusa). Rotina de limpeza que trunque o schema inteiro precisa
         desligar os triggers antes, como tests/test_concorrencia.py já faz
         desde a 016.

    DADO A CONFERIR ANTES, que esta migration deliberadamente NÃO corrige
    sozinha: baixas já gravadas com movimento de valor insuficiente, que só
    poderiam ter entrado por SQL direto (`fn_baixar_parcela` sempre recusou).

        select p.operacao_id, p.numero, p.valor_total, m.valor, m.documento
          from parcela p
          join movimento_bancario m on m.id = p.movimento_id
         where m.valor < p.valor_total;

    Havendo linhas, a guarda nova não as toca — ela é BEFORE ROW e só olha o
    que está sendo escrito agora — e elas seguem contando como pagas no aging
    (008) e na apuração (011). Reverter uma baixa é justamente o que este
    sistema não faz (não há estorno definido, ver o topo da 009), então o
    tratamento é de negócio: reconciliar contra o extrato e, se o dinheiro não
    entrou mesmo, encerrar a operação pela baixa como prejuízo. Escolher isso
    dentro de uma migration seria o banco decidindo o que só o dono do negócio
    pode decidir.
    """
    sql = (_SQL_DIR / "027_bordas_da_cobranca_2.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Derruba a guarda de INSERT, devolve `fn_parcela_imutavel` à versão da
    016 e restaura a chave única global de `movimento_bancario`.

    NÃO É DESTRUTIVO NO DADO, MAS REABRE OS TRÊS FUROS, e isto precisa estar
    escrito onde quem digita o comando lê: descer daqui devolve a agenda que
    aceita apêndice, a baixa que se faz contra um centavo por UPDATE direto e a
    importação que descarta em silêncio o crédito do segundo banco.

    E TEM UMA CONDIÇÃO DE DADO QUE PODE FAZER O DOWNGRADE FALHAR — a única
    desta migration, e ela falha do lado seguro. `add constraint ... unique
    (documento)` valida a tabela inteira: se, com a 027 no ar, entraram dois
    movimentos de contas diferentes com o mesmo FITID (exatamente o caso que
    ela existe para permitir), a restauração da chave global aborta com 23505.
    Conferir antes:

        select documento, count(*)
          from movimento_bancario
         group by documento having count(*) > 1;

    Havendo linhas, NÃO há saída automática: apagar uma delas é destruir lastro
    bancário de uma baixa possivelmente já feita, e `movimento_bancario` é
    imutável (OC012). O downgrade simplesmente não é aplicável nessa base, e a
    falha do ADD CONSTRAINT é a forma correta de dizer isso.

    A ORDEM É A INVERSA DO UPGRADE — triggers, função, chave —, e a função vem
    do SQL da 016 reaplicado por inteiro: ele recria `fn_parcela_imutavel` na
    forma anterior (sem a cobertura) e reaplica, idempotentemente, o CHECK de
    domínio, a coluna `baixado_por` e os bloqueios de TRUNCATE das CINCO tabelas
    que ela cobre, que já estão no lugar e não são afetados.

    O BLOQUEIO DE TRUNCATE EM `parcela` PRECISA SER DERRUBADO AQUI, e é a razão
    de esta linha existir em vez de confiar na reaplicação da 016: a 016 não
    conhece essa tabela — o trigger é da 027 —, então reaplicá-la não o remove.
    Sem o drop explícito, descer da 027 deixaria para trás uma guarda que a
    migration de destino nunca instalou, e o schema pararia de ser função da
    versão. `fn_bloquear_truncate_append_only` NÃO é dropada: ela é da 016 e
    continua servindo as outras cinco tabelas.
    """
    op.execute("drop trigger if exists trg_parcela_insercao on parcela")
    op.execute("drop function if exists fn_parcela_insercao_valida()")
    op.execute("drop trigger if exists trg_bloquear_truncate_parcela on parcela")
    op.execute((_SQL_DIR / "016_bordas_da_cobranca.sql").read_text(encoding="utf-8"))
    op.execute("""
        alter table movimento_bancario
            drop constraint if exists movimento_documento_por_conta
    """)
    op.execute("""
        alter table movimento_bancario
            add constraint movimento_documento_unico unique (documento)
    """)
