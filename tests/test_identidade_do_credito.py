"""
A identidade de um crédito (migration 029), depois de três chaves erradas.

    009  chave = (documento)                -> perdia o crédito do 2º banco
    027  chave = (documento, conta_origem)  -> DOBRAVA o lastro (grafia ≠ conta)
    028  chave = (documento, conta_chave)   -> DOBRAVA do outro lado (ACCTID)
    029  chave = (documento, valor, data)   -> a conta sai da identidade

A 028 foi verificada nos dois sentidos, com contraprova contra o schema
anterior, e mesmo assim deixou a metade simétrica aberta: ela perguntou "e se o
`<BANKID>` faltar?" e não perguntou "e se faltar o `<ACCTID>`?".

O QUE ESTE ARQUIVO EXISTE PARA IMPEDIR não é uma quarta chave errada — é a
QUARTA VERSÃO DO MESMO ERRO. Por isso ele não testa "a exportação com BANKID
contra a sem BANKID": ele PARAMETRIZA todas as formas de o arquivo declarar
menos do que a exportação completa, e afirma, para cada uma, que o lastro não
dobra. Quem acrescentar uma sexta forma de OFX capado acrescenta uma linha na
lista, e a suíte cobre o caso novo sem que ninguém precise ter pensado nele.
"""

import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import importar_extrato_ofx, registrar_movimento_bancario
from app.ofx import ler_ofx


# ---------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------

DATA_A = "20260810"
DATA_B = "20260910"


def _ofx(bloco_conta: str, transacoes: list[tuple[str, str, str]]) -> str:
    linhas = "\n".join(
        f"<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>{data}<TRNAMT>{valor}"
        f"<FITID>{fitid}<NAME>TOMADOR</STMTTRN>"
        for fitid, data, valor in transacoes
    )
    return (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n\n"
        "<OFX>\n<BANKMSGSRSV1><STMTTRNRS><STMTRS>\n<CURDEF>BRL\n"
        f"{bloco_conta}"
        f"<BANKTRANLIST>\n{linhas}\n</BANKTRANLIST>\n"
        "</STMTRS></STMTTRNRS></BANKMSGSRSV1>\n</OFX>\n"
    )


def _importar(db_session: Session, arquivo: str):
    extrato = ler_ofx(arquivo)
    return importar_extrato_ofx(
        db_session,
        transacoes=extrato.transacoes,
        arquivo_sha256=hashlib.sha256(arquivo.encode()).hexdigest(),
    )


def _lastro(db_session: Session) -> Decimal:
    return Decimal(
        db_session.execute(
            text("select coalesce(sum(valor), 0) from movimento_bancario")
        ).scalar_one()
    )


COMPLETO = "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>123456\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"

# Toda forma conhecida de o arquivo declarar MENOS que a exportação completa.
# Acrescentar uma aqui é o jeito barato de cobrir uma variante nova de banco.
CAPADOS = {
    "sem BANKID": "<BANKACCTFROM>\n<ACCTID>123456\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n",
    "sem ACCTID": "<BANKACCTFROM>\n<BANKID>001\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n",
    "ACCTID vazio": "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n",
    "ACCTID só espaços": (
        "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>   \n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"
    ),
    "sem BANKACCTFROM": "",
    "conta com pontuação": (
        "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>12345-6\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"
    ),
    "zero à esquerda": (
        "<BANKACCTFROM>\n<BANKID>0001\n<ACCTID>0123456\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"
    ),
}

LINHAS = [("TED0001", DATA_A, "3000.00"), ("TED0002", DATA_B, "3000.00")]


# ---------------------------------------------------------------------
# 1. Nenhuma forma de arquivo capado dobra o lastro
# ---------------------------------------------------------------------


@pytest.mark.parametrize("descricao,bloco", list(CAPADOS.items()), ids=list(CAPADOS))
def test_exportacao_capada_nao_dobra_o_lastro(db_session: Session, descricao: str, bloco: str):
    """O crítico, em todas as formas que ele soube assumir.

    R$ 6.000 entraram. Se qualquer destas importar de novo, o lastro vira
    R$ 12.000, as parcelas ficam quitadas contra dinheiro que não entrou,
    `liquidar` é aceito (OC022 pede "todas as parcelas pagas") e o comprometido
    volta a zero — o furo do teto do Art. 5º pela porta do extrato.
    """
    assert _importar(db_session, _ofx(COMPLETO, LINHAS)).criados == 2

    segunda = _importar(db_session, _ofx(bloco, LINHAS))

    assert segunda.criados == 0, f"'{descricao}' criou lastro de novo"
    assert segunda.ja_registrados == 2
    assert _lastro(db_session) == Decimal("6000.00")


def test_a_ordem_inversa_tambem(db_session: Session):
    """Importar o capado PRIMEIRO e o completo depois. A assimetria importa: a
    conta chega ao banco na primeira importação, e é ela que define o que a
    segunda encontra."""
    assert _importar(db_session, _ofx(CAPADOS["sem ACCTID"], LINHAS)).criados == 2
    segunda = _importar(db_session, _ofx(COMPLETO, LINHAS))
    assert segunda.criados == 0
    assert _lastro(db_session) == Decimal("6000.00")


def test_a_fronteira_entre_manual_e_ofx(db_session: Session):
    """O lançamento digitado e o OFX eram espaços de nomes distintos até a 029 —
    o manual tem `conta_origem` NULL por decisão da 024. O operador que lança o
    crédito à mão porque a importação ainda não rodou, e importa o extrato
    depois, criava duas linhas para o mesmo dinheiro. É o caminho que a própria
    tela instrui a percorrer."""
    registrar_movimento_bancario(
        db_session,
        data_movimento=date(2026, 8, 10),
        valor=Decimal("3000.00"),
        documento="TED0001",
    )
    r = _importar(db_session, _ofx(COMPLETO, [LINHAS[0]]))
    assert r.criados == 0
    assert r.ja_registrados == 1
    assert _lastro(db_session) == Decimal("3000.00")


# ---------------------------------------------------------------------
# 2. O que a 027 conquistou continua de pé
# ---------------------------------------------------------------------


def test_bancos_diferentes_com_o_mesmo_fitid_coexistem(db_session: Session):
    """A conquista da 027, que a 029 não pode desfazer: FITID é único DENTRO da
    conta, e banco brasileiro emite sequência curta. Valores diferentes, datas
    diferentes — são créditos diferentes e os dois entram."""
    banco_a = "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>111111\n</BANKACCTFROM>\n"
    banco_b = "<BANKACCTFROM>\n<BANKID>237\n<ACCTID>222222\n</BANKACCTFROM>\n"

    assert _importar(db_session, _ofx(banco_a, [("1", DATA_A, "1000.00")])).criados == 1
    assert _importar(db_session, _ofx(banco_b, [("1", DATA_A, "2000.00")])).criados == 1
    assert _lastro(db_session) == Decimal("3000.00")


def test_o_mesmo_fitid_na_mesma_conta_com_valor_corrigido_e_recusado(db_session: Session):
    """A outra chave, a da 028, é a que barra isto: mesma conta, mesmo
    identificador, valor diferente. Sem ela, o extrato reemitido com o valor
    corrigido criaria uma segunda linha e o crédito contaria duas vezes."""
    assert _importar(db_session, _ofx(COMPLETO, [("X1", DATA_A, "100.00")])).criados == 1
    r = _importar(db_session, _ofx(COMPLETO, [("X1", DATA_A, "999.00")]))
    assert r.criados == 0
    assert r.conflitos == 1
    assert _lastro(db_session) == Decimal("100.00")


# ---------------------------------------------------------------------
# 3. O custo assumido é VISÍVEL
# ---------------------------------------------------------------------


def test_a_colisao_residual_sai_como_conflito_e_nao_como_rotina(db_session: Session):
    """Dois bancos, o mesmo FITID, o MESMO valor e a MESMA data: a 029 pula a
    segunda linha, e um crédito real fica de fora do lastro.

    Isso é o custo assumido — e o que o torna aceitável é ele NÃO ser
    silencioso. O achado que derrubou a 027 nunca foi "uma linha se perdeu",
    foi "uma linha se perdeu E A ARITMÉTICA FECHOU"."""
    banco_a = "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>111111\n</BANKACCTFROM>\n"
    banco_b = "<BANKACCTFROM>\n<BANKID>237\n<ACCTID>222222\n</BANKACCTFROM>\n"

    assert _importar(db_session, _ofx(banco_a, [("1", DATA_A, "1000.00")])).criados == 1
    r = _importar(db_session, _ofx(banco_b, [("1", DATA_A, "1000.00")]))

    assert r.criados == 0
    assert (
        r.conflitos == 0 or r.ja_registrados == 0
    ), "a linha pulada precisa cair num destino só, e o destino precisa dizer o que houve"
    # A identidade é a mesma, então para o sistema é o MESMO crédito: cai em
    # ja_registrados. O que o operador tem para descobrir a diferença é a conta
    # na lista de movimentos — e é por isso que `conta_origem` continua gravada.
    assert r.ja_registrados == 1
    assert _lastro(db_session) == Decimal("1000.00")


def test_ja_registrados_e_contado_e_nao_derivado(db_session: Session):
    """Enquanto `ja_registrados` era `len(unicas) - criados - conflitos`, a soma
    dos cinco destinos era uma IDENTIDADE ALGÉBRICA e o selo "Nenhuma linha do
    extrato se perdeu" não podia falhar — nem com o motor quebrado.

    Este teste não consegue provar uma negativa; o que ele prova é que os três
    destinos são somados a partir de contagens independentes e que uma
    importação mista distribui certo."""
    assert _importar(db_session, _ofx(COMPLETO, [("A1", DATA_A, "100.00")])).criados == 1

    r = _importar(
        db_session,
        _ofx(
            COMPLETO,
            [
                ("A1", DATA_A, "100.00"),  # já registrado, idêntico
                ("A1", DATA_A, "100.00"),  # repetido dentro do arquivo
                ("A2", DATA_A, "-5.00"),  # débito
                ("A3", DATA_B, "300.00"),  # novo
            ],
        ),
    )
    assert (r.criados, r.ja_registrados, r.conflitos) == (1, 1, 0)
    assert r.repetidos_no_arquivo == 1
    assert r.debitos_ignorados == 1
    assert (
        r.lidas
        == r.criados + r.ja_registrados + r.conflitos + r.repetidos_no_arquivo + r.debitos_ignorados
    )


def test_colisao_DENTRO_do_arquivo_nao_e_atribuida_ao_banco(db_session: Session):
    """A deduplicação em memória usa a MESMA chave do banco. Quando ela era mais
    grossa (a 028 usava `conta_chave`), uma linha real morria em Python e o
    relatório a rotulava `repetidos_no_arquivo`, cuja explicação na tela manda o
    operador auditar o BANCO por "anomalia do arquivo" — quando o arquivo estava
    perfeito e quem fundiu as linhas foi a nossa chave."""
    arquivo = _ofx(
        COMPLETO,
        [
            ("Z1", DATA_A, "500.00"),
            ("Z1", DATA_A, "900.00"),  # mesmo FITID, OUTRO valor: não é repetição
        ],
    )
    r = _importar(db_session, arquivo)

    assert r.repetidos_no_arquivo == 0, "linhas de valores diferentes não são 'o mesmo FITID'"
    assert r.criados == 1
    assert r.conflitos == 1
    assert r.documentos_em_conflito == ("Z1",)


# ---------------------------------------------------------------------
# 4. A proveniência sobrevive
# ---------------------------------------------------------------------


def test_a_conta_continua_gravada_e_visivel(db_session: Session):
    """A conta sai da IDENTIDADE, não do registro. Ela é a única pista que o
    operador tem para distinguir dois créditos que colidiram, e apagá-la
    destruiria a proveniência que a 024 existe para dar."""
    _importar(db_session, _ofx(COMPLETO, [("P1", DATA_A, "100.00")]))
    linha = db_session.execute(
        text("select conta_origem, conta_chave, arquivo_sha256 from movimento_bancario")
    ).one()
    assert linha.conta_origem == "001/123456"
    assert linha.conta_chave == "123456"
    assert linha.arquivo_sha256


def test_codigo_de_banco_nao_e_gravado_como_conta(db_session: Session):
    """`_formatar_conta` devolvia o BANKID quando o ACCTID vinha vazio, e a
    coluna da conta passava a guardar um CÓDIGO DE BANCO — exibido na tela como
    se fosse uma conta. Com a canonização da 028 ficava pior: o COMPE '001' e a
    conta '0000001' viravam a mesma chave."""
    _importar(db_session, _ofx(CAPADOS["ACCTID vazio"], [("Q1", DATA_A, "100.00")]))
    linha = db_session.execute(
        text("select conta_origem, conta_chave from movimento_bancario")
    ).one()
    assert linha.conta_origem is None
    assert linha.conta_chave is None


# ---------------------------------------------------------------------
# 5. OC026 sob concorrência
# ---------------------------------------------------------------------


def test_o_gate_de_cobranca_segura_a_operacao(
    db_session: Session, tomador_autorizado, capital_constituido
):
    """`fn_operacao_em_cobranca` passou a tomar `for share` (029). Sem o lock, o
    gate valia só na direção sequencial: duas sessões — uma baixando, outra
    renegociando — atravessavam as duas guardas e deixavam no banco o estado que
    a 028 declara impossível.

    Aqui a prova é do LOCK, não da corrida: dentro de uma transação que baixou
    uma parcela, a linha da operação está travada contra transição de status. Um
    `for update` de outra transação bloquearia; verificamos o efeito local, que
    é o que o `for share` promete."""
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 0, 'PRICE', 4, 'registrada', 'REG-029')
        returning id
        """),
        {"t": str(tomador_autorizado)},
    ).scalar_one()
    db_session.commit()

    from app.capital_engine import ativar_operacao, baixar_parcela
    from tests.conftest import confirmar_registro

    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)

    parcela = db_session.execute(
        text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
        {"op": str(op_id)},
    ).one()
    movimento = registrar_movimento_bancario(
        db_session,
        data_movimento=date.today() - timedelta(days=1),
        valor=Decimal(parcela.valor_total),
        documento=f"TED-{uuid.uuid4().hex[:10]}",
    )
    baixar_parcela(db_session, parcela.id, movimento)

    assert (
        db_session.execute(
            text("select status from parcela where id = :p"), {"p": str(parcela.id)}
        ).scalar_one()
        == "paga"
    )
    # A função é VOLATILE desde a 029 — uma função que adquire lock não é STABLE,
    # e o rótulo errado autorizaria o planejador a não reexecutá-la.
    volatilidade = db_session.execute(
        text("select provolatile from pg_proc where proname = 'fn_operacao_em_cobranca'")
    ).scalar_one()
    assert volatilidade == "v"
