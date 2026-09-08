"""028 - a identidade da conta (e não a grafia dela) forma a chave do extrato;
a baixa passa a exigir operação EM COBRANÇA (OC026); e as três tabelas
append-only que ficaram de fora ganham guarda de TRUNCATE.

Fecha o CRÍTICO que a própria 027 abriu: `conta_origem` é a grafia que o
arquivo trouxe, não a identidade da conta, e com ela na chave o mesmo extrato
exportado com e sem `<BANKID>` importa duas vezes — dobrando o lastro, quitando
a carteira contra dinheiro que não entrou e devolvendo o capital ao teto do
Art. 5º por `liquidar`.

Baseline convertido de migrations/028_identidade_da_conta.sql.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-27
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Uma coluna gerada, uma troca de chave, duas funções recriadas e três
    triggers de TRUNCATE.

    ESTA MIGRATION PODE FALHAR EM BASE COM DADOS, e é a primeira da série em que
    isso é o comportamento CORRETO — não uma fragilidade. A 027 podia prometer
    aplicação garantida porque a chave dela era mais FRACA que a anterior
    (`unique (documento)` implica `unique (documento, conta_origem)`). Aqui é o
    contrário: `(documento, conta_chave)` UNE o que a 027 separava, então
    qualquer par de linhas que só existe por causa do defeito viola a chave nova
    e o `ADD CONSTRAINT` aborta.

    Abortar é o único desfecho honesto. Escolher qual das duas linhas duplicadas
    é a real, e o que fazer com as parcelas que uma delas já baixou, não é
    decisão de migration — `movimento_bancario` é imutável (OC012) e a baixa não
    tem estorno (009). CONFERIR ANTES:

        select fn_conta_chave(conta_origem) as conta_chave,
               documento, count(*), array_agg(id), array_agg(conta_origem),
               array_agg(valor), array_agg(arquivo_sha256)
          from movimento_bancario
         group by 1, 2
        having count(*) > 1;

    (a função `fn_conta_chave` é criada pela própria migration, então rode a
    consulta com o corpo dela inline, ou aplique num clone do banco primeiro.)

    Havendo linhas, cada grupo é um crédito contado mais de uma vez. O caminho
    é de negócio: identificar qual movimento lastreou qual baixa, e conciliar.

    O QUE ESPERAR DEPOIS DE SUBIR:

      1. `movimento_bancario` ganha `conta_chave`, GERADA a partir de
         `conta_origem`. `conta_origem` não muda e continua sendo o que a tela
         mostra — ela é proveniência. A chave passa a ser (documento,
         conta_chave);

      2. reimportar o mesmo extrato exportado com outra grafia da conta deixa de
         criar linha nova e passa a contar como `ja_registrados`. É o conserto:
         antes disso, essa reimportação DOBRAVA o lastro;

      3. `POST /api/cobranca/parcelas/{id}/baixar` passa a recusar com OC026 a
         parcela de operação que não esteja 'ativa' ou 'inadimplente'. Nenhum
         fluxo legítimo é atingido — a agenda de uma operação em cobrança está,
         por definição, em cobrança —, mas a agenda de um título JÁ RENEGOCIADO
         deixa de aceitar baixa, que é o alto que isto fecha;

      4. `truncate` em `contrato_emprestimo`, `registro_operacao` e
         `apuracao_fiscal` passa a ser recusado (OC017, OC018, OC016). Rotina de
         limpeza que trunque o schema inteiro precisa desligar os triggers
         antes, como tests/test_concorrencia.py já faz desde a 016.
    """
    sql = (_SQL_DIR / "028_identidade_da_conta.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Devolve a chave à grafia, a baixa ao estado sem gate de operação, e
    remove as três guardas de TRUNCATE.

    NÃO É DESTRUTIVO E NÃO PODE FALHAR POR DADO — o inverso exato do upgrade, e
    a razão é a mesma simetria: `conta_chave` é função de `conta_origem`, logo
    duas linhas com a mesma `conta_origem` têm a mesma `conta_chave`. Se a chave
    da 028 está de pé, não existe par duplicado em (documento, conta_origem), e
    a chave da 027 entra sem validar nada de novo.

    REABRE O CRÍTICO, e isto precisa estar escrito onde quem digita o comando
    lê: descer daqui devolve a importação que dobra o lastro quando a mesma
    conta chega escrita de dois jeitos, e o lastro dobrado quita a carteira e
    devolve o capital ao teto.

    A ORDEM É OBRIGATÓRIA nos três primeiros passos: a constraint depende da
    coluna, e a coluna gerada depende da função. Dropar fora de ordem exige
    CASCADE, que aqui derrubaria mais do que se quer.

    Os dois arquivos reaplicados fazem o trabalho de restauração e são
    idempotentes: a 016 devolve `fn_baixar_parcela` sem o gate OC026 e
    `fn_parcela_imutavel` à forma dela; a 027, aplicada em seguida, devolve
    `fn_parcela_imutavel` à forma COM a cobertura de valor e recria a chave
    (documento, conta_origem) — é dela que sai a chave antiga, e por isso não há
    `add constraint` escrito aqui.
    """
    op.execute("drop trigger if exists trg_bloquear_truncate_contrato on contrato_emprestimo")
    op.execute("drop trigger if exists trg_bloquear_truncate_registro on registro_operacao")
    op.execute("drop trigger if exists trg_bloquear_truncate_apuracao on apuracao_fiscal")

    # A VIEW SAI PRIMEIRO. Ela seleciona `conta_chave`, e o Postgres recusa
    # dropar a coluna enquanto ela existir (DependentObjectsStillExist). Sem
    # CASCADE de propósito: cascata aqui derrubaria qualquer outra coisa que um
    # dia venha a depender da coluna, em silêncio, e a lista de dependências é
    # justamente o que se quer ver falhar quando ela crescer.
    op.execute("drop view if exists v_movimento_por_identidade")
    op.execute("""
        alter table movimento_bancario
            drop constraint if exists movimento_documento_por_conta
    """)
    op.execute("alter table movimento_bancario drop column if exists conta_chave")
    op.execute("drop function if exists fn_conta_chave(text)")

    op.execute((_SQL_DIR / "016_bordas_da_cobranca.sql").read_text(encoding="utf-8"))
    op.execute((_SQL_DIR / "027_bordas_da_cobranca_2.sql").read_text(encoding="utf-8"))

    # Depois das duas reaplicações, para que nada mais dependa dela.
    op.execute("drop function if exists fn_operacao_em_cobranca(uuid)")
