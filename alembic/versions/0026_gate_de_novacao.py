"""026 - gate de novação: a substituta tem que cobrir o saldo devedor da
original (OC024), e a original só sai do comprometido quando a substituta é
ATIVADA — nunca antes.

Fecha o furo em que renegociar R$ 30.000 por R$ 0,01, com as doze parcelas em
aberto e zero centavo comprovado, devolvia os R$ 30.000 inteiros ao teto do
Art. 5º da LC 167/2019 e permitia pôr R$ 80.000 na rua sobre R$ 50.000 de
capital próprio.

Baseline convertido de migrations/026_gate_de_novacao.sql.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-23
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """Uma função nova e duas recriadas. Nenhuma tabela alterada, nenhum dado
    tocado, nenhum back-fill possível ou necessário.

    O UPGRADE É SEGURO EM BASE COM DADOS, e vale conferir por quê antes de
    rodar: `create or replace function` troca o corpo sem tocar em linha
    nenhuma, e a 026 não acrescenta constraint (que validaria a tabela
    inteira e poderia falhar com 23514, como a 017 avisa para o CHECK de
    status). O que muda é o comportamento dos próximos atos.

    O QUE ESPERAR DEPOIS DE SUBIR, para ninguém tratar como incidente:

      1. `POST /operacoes/{id}/renegociar` passa a devolver 422 com código
         OC024 quando a substituta é menor que o saldo devedor da original.
         Renegociações que ANTES passavam por qualquer valor agora precisam
         cobrir o principal ainda não amortizado contra movimento bancário.
         É a correção, não uma regressão;

      2. a original NÃO fica mais em 'renegociada' no ato da chamada. Ela
         permanece 'ativa'/'inadimplente' — no comprometido, no aging e na
         cobrança — até a substituta ser ATIVADA. A tela de operações vai
         mostrar as duas: a original ainda viva e a substituta 'registrada'
         aguardando ativação. É o desenho escolhido (justificado por extenso
         no cabeçalho do .sql): enquanto o novo título não está registrado e
         ativo, a novação não se consumou;

      3. no capital_ledger, o evento 'renegociacao' deixa de aparecer no
         instante da chamada de novação e passa a aparecer no instante da
         ativação da substituta, imediatamente antes do 'ativacao_operacao'
         dela, no mesmo commit. Séries temporais já gravadas não mudam —
         nenhum evento é reescrito nem apagado.

    NOVAÇÕES PENDENTES NO MOMENTO DO DEPLOY, que é a única situação de dado
    que exige atenção: uma base em que já existe original 'renegociada' com
    substituta 'registrada' (novada sob a regra antiga) fica com a substituta
    ÓRFÃ — ativá-la passa a ser recusado com OC024, porque a original já não
    ocupa o teto e não há lugar a substituir. É a recusa correta: aquele teto
    já foi indevidamente liberado, e ativar a substituta em cima disso somaria
    o mesmo dinheiro duas vezes. Conferir antes de subir com:

        select o.id as substituta, o.valor_principal, r.id as original, r.status
        from operacao_credito o
        join operacao_credito r on r.id = o.substitui_operacao_id
        where o.status = 'registrada';

    Havendo linhas, a decisão é de negócio (cancelar a substituta e refazer a
    novação, ou aportar capital), não de migration — e por isso não há
    back-fill automático aqui: escolher sozinho entre essas duas saídas seria
    o banco decidindo o que só o dono do negócio pode decidir.

    A DEPENDÊNCIA DA 017 É REAL: `fn_check_teto_capital` é recopiada INTEIRA a
    partir da versão da 017 (gate de quitação OC022, write-off no conjunto do
    comprometido, evento 'baixa_prejuizo'). `down_revision = "0025"` já
    garante a ordem.
    """
    sql = (_SQL_DIR / "026_gate_de_novacao.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Reaplica o SQL da 017 e o da 006, nesta ordem, e derruba a função nova.

    NÃO É DESTRUTIVO NO DADO — nenhuma linha é tocada — MAS REABRE O FURO, e
    isto precisa estar escrito onde quem digita o comando lê: descer daqui
    devolve `fn_novar_operacao` à versão que aceita qualquer valor e baixa a
    original antes de a substituta existir. Voltar para cá é voltar a poder
    emprestar de novo o dinheiro que está na rua.

    A ORDEM É 006 PRIMEIRO E 017 POR CIMA, e não o contrário, porque as duas
    definem funções em comum e vale a ÚLTIMA aplicação — ler estas duas linhas
    invertidas é reabrir o furo da 017 ao consertar o da 026:

      - `017_gate_de_liquidacao.sql` devolve a versão anterior de
        `fn_check_teto_capital` (que é a versão vigente antes da 026) e
        reaplica, idempotentemente, o CHECK de status, o gate de redução e o
        congelamento da 015;
      - `006_novacao_e_inadimplencia.sql` devolve a versão anterior de
        `fn_novar_operacao`. Ele TAMBÉM recria `fn_check_teto_capital` e
        `fn_check_reducao_capital` na forma da 006 — sem o gate de quitação
        OC022 e sem 'baixada_prejuizo' no comprometido —, o que reabriria o
        furo da 017 por tabela. Por isso a 017 é reaplicada DEPOIS, e o SQL
        dela é executado por último para ficar por cima.

    `fn_saldo_devedor_com_lastro` é derrubada por último: enquanto a versão
    026 das funções estiver instalada, elas a referenciam.
    """
    op.execute((_SQL_DIR / "006_novacao_e_inadimplencia.sql").read_text(encoding="utf-8"))
    op.execute((_SQL_DIR / "017_gate_de_liquidacao.sql").read_text(encoding="utf-8"))
    op.execute("drop function if exists fn_saldo_devedor_com_lastro(uuid)")
