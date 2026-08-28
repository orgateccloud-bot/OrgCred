"""
A identidade do crédito, por EIXO e não por caso (migration 030).

QUATRO CHAVES ERRADAS SEGUIDAS, e a quarta foi encontrada exatamente pela
pergunta que este arquivo existe para responder:

    009  (documento)                -> perdia o crédito do 2º banco
    027  (documento, conta_origem)  -> DOBRAVA (grafia da conta)
    028  (documento, conta_chave)   -> DOBRAVA (metade do ACCTID)
    029  (documento, valor, data)   -> DOBRAVA (grafia do FITID, fuso da data)

A 029 tirou a conta da identidade com o argumento certo — "exportações
diferentes escrevem o mesmo fato de formas diferentes" — e não fez a mesma
pergunta aos dois campos que ficaram. O teste dela parametrizava SETE formas de
conta capada e ZERO formas de FITID e de data: enumerava com rigor o eixo já
consertado.

POR ISSO ESTE ARQUIVO NÃO LISTA CASOS: ele lista EIXOS, e cruza todos com
todos. A afirmação é uma só, e é a que os quatro defeitos violaram —

    o MESMO crédito, escrito de QUALQUER combinação de formas, é UM crédito.

Um eixo novo (um campo, um formato de exportação) entra como uma entrada de
dicionário e o produto cartesiano cobre as combinações sozinho. Foi a ausência
desse produto que deixou passar a 029: 'sem ACCTID' já estava na lista, o fuso
não estava, e é o cruzamento dos dois que dobra o lastro.
"""

import hashlib
import itertools
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import importar_extrato_ofx
from app.ofx import chave_texto, conta_chave, documento_chave, ler_ofx


# ---------------------------------------------------------------------
# Os eixos. Cada entrada é uma forma DIFERENTE de escrever o MESMO crédito.
# ---------------------------------------------------------------------

CONTA = {
    "completa": "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>123456\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n",
    "sem BANKID": "<BANKACCTFROM>\n<ACCTID>123456\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n",
    "sem ACCTID": "<BANKACCTFROM>\n<BANKID>001\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n",
    "ACCTID vazio": "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n",
    "sem bloco": "",
    "com pontuação": (
        "<BANKACCTFROM>\n<BANKID>001\n<ACCTID>12345-6\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"
    ),
    "zero à esquerda": (
        "<BANKACCTFROM>\n<BANKID>0001\n<ACCTID>0123456\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"
    ),
}

FITID = {
    "maiúscula": "TED1",
    "minúscula": "ted1",
    "zero à esquerda": "0TED1",
    "com espaço": "TED 1",
    "com hífen": "TED-1",
    "misto": "0ted-1",
}

# O MESMO INSTANTE, escrito de formas diferentes. 22h de 10/08 em BRT é 01h de
# 11/08 em GMT — e o crédito é do dia 10 para a ESC, nos dois casos.
DATA = {
    "só a data": "20260810",
    "hora sem fuso": "20260810220000",
    "BRT": "20260810220000.000[-3:BRT]",
    "GMT": "20260811010000.000[0:GMT]",
    "fuso positivo": "20260811050000.000[+4:GST]",
}

VALOR = "3000.00"


def _ofx(conta: str, fitid: str, dtposted: str) -> str:
    return (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n\n"
        "<OFX>\n<BANKMSGSRSV1><STMTTRNRS><STMTRS>\n<CURDEF>BRL\n"
        f"{conta}"
        "<BANKTRANLIST>\n"
        f"<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>{dtposted}<TRNAMT>{VALOR}"
        f"<FITID>{fitid}<NAME>TOMADOR</STMTTRN>\n"
        "</BANKTRANLIST>\n"
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


# ---------------------------------------------------------------------
# A afirmação, cruzando todos os eixos
# ---------------------------------------------------------------------

# 7 contas × 6 identificadores × 5 datas = 210 formas de escrever o mesmo
# crédito. O produto é o ponto: 'sem ACCTID' sozinho já era testado antes da
# 029, e o que dobrava o lastro era ele CRUZADO com o fuso.
COMBINACOES = list(itertools.product(CONTA, FITID, DATA))


@pytest.mark.parametrize("conta,fitid,dtposted", COMBINACOES, ids=lambda v: str(v))
def test_o_mesmo_credito_escrito_de_outro_jeito_e_um_credito(
    db_session: Session, conta: str, fitid: str, dtposted: str
):
    """R$ 3.000 entraram UMA vez. Nenhuma combinação pode fazê-los virar dois.

    Cada duplicação aqui é o furo do teto do Art. 5º: lastro dobrado quita
    parcela que ninguém pagou, `liquidar` é aceito (OC022 pede "todas as
    parcelas pagas") e o capital volta ao teto contra dinheiro que não entrou.
    """
    primeira = _ofx(CONTA["completa"], FITID["maiúscula"], DATA["só a data"])
    assert _importar(db_session, primeira).criados == 1

    segunda = _ofx(CONTA[conta], FITID[fitid], DATA[dtposted])
    resultado = _importar(db_session, segunda)

    assert (
        resultado.criados == 0
    ), f"conta={conta!r} fitid={fitid!r} data={dtposted!r} criou uma segunda linha"
    assert _lastro(db_session) == Decimal(VALOR)


def test_creditos_realmente_diferentes_continuam_entrando(db_session: Session):
    """A guarda tem que barrar a REESCRITA e deixar passar o crédito NOVO. Uma
    que recusa o caminho legítimo é tão defeito quanto a que duplica."""
    assert _importar(db_session, _ofx(CONTA["completa"], "TED1", "20260810")).criados == 1
    # Outro identificador, mesmo valor e data: outro pagamento, do mesmo dia.
    assert _importar(db_session, _ofx(CONTA["completa"], "TED2", "20260810")).criados == 1
    # Mesmo identificador e valor, OUTRO dia: o banco não reusa FITID, então é
    # outro crédito — e a chave por conta o barra, o que é o comportamento
    # declarado (extrato reemitido com valor/data corrigidos).
    r = _importar(db_session, _ofx(CONTA["completa"], "TED1", "20260901"))
    assert r.criados == 0 and r.conflitos == 1
    assert _lastro(db_session) == Decimal("6000.00")


# ---------------------------------------------------------------------
# O espelho Python × SQL, agora sobre os DOIS campos canônicos
# ---------------------------------------------------------------------

TEXTOS = [
    "TED1",
    "ted1",
    "0TED1",
    "TED 1",
    "TED-1",
    "0ted-1",
    "000",
    "0",
    "---",
    "abc",
    "001/123456",
    "123456",
    "",
]


@pytest.mark.parametrize("bruto", TEXTOS)
def test_a_normalizacao_do_python_e_a_do_banco_concordam(db_session: Session, bruto: str):
    """Duas implementações da mesma regra é dívida; o que a torna honesta é este
    teste. Sem ele, uma divergência sutil faria a deduplicação em memória
    discordar da chave do banco em silêncio — que é a classe de defeito que
    estas quatro migrations existem para consertar."""
    do_banco = db_session.execute(
        text("select fn_chave_texto(cast(:t as text))"), {"t": bruto}
    ).scalar_one()
    assert do_banco == chave_texto(bruto), f"fn_chave_texto divergiu para {bruto!r}"

    if bruto:
        do_banco_doc = db_session.execute(
            text("select fn_documento_chave(cast(:t as text))"), {"t": bruto}
        ).scalar_one()
        assert do_banco_doc == documento_chave(bruto), f"fn_documento_chave divergiu para {bruto!r}"

    do_banco_conta = db_session.execute(
        text("select fn_conta_chave(cast(:t as text))"), {"t": bruto}
    ).scalar_one()
    assert do_banco_conta == conta_chave(bruto), f"fn_conta_chave divergiu para {bruto!r}"


def test_zeros_a_esquerda_preservam_um_caractere(db_session: Session):
    """'000' e '0' precisam ser a mesma coisa. Com `^0+` puro, '000' virava
    string vazia e caía no fallback verbatim — deixando '000' e '0000'
    distintos, que é a direção perigosa (separar o que é igual)."""
    assert chave_texto("000") == "0"
    assert chave_texto("0") == "0"
    assert chave_texto("0001") == "1"
    assert (
        db_session.execute(text("select fn_chave_texto('000')")).scalar_one()
        == db_session.execute(text("select fn_chave_texto('0')")).scalar_one()
    )


def test_documento_que_canoniza_para_vazio_cai_no_verbatim(db_session: Session):
    """`documento` é NOT NULL e precisa continuar identificando: um FITID só de
    pontuação não pode virar NULL, ou duas linhas sem nada em comum
    colidiriam."""
    assert documento_chave("---") == "---"
    assert db_session.execute(text("select fn_documento_chave('---')")).scalar_one() == "---"


# ---------------------------------------------------------------------
# A proveniência sobrevive à canonização
# ---------------------------------------------------------------------


def test_o_verbatim_continua_gravado_dos_dois_lados(db_session: Session):
    """O canônico é a identidade; o verbatim é o que o operador procura no
    extrato de papel. Apagá-lo tornaria o aviso de conflito um enigma."""
    _importar(db_session, _ofx(CONTA["completa"], "0ted-1", "20260810"))
    linha = db_session.execute(
        text("select documento, documento_chave, conta_origem, conta_chave from movimento_bancario")
    ).one()
    assert linha.documento == "0ted-1"
    assert linha.documento_chave == "TED1"
    assert linha.conta_origem == "001/123456"
    assert linha.conta_chave == "123456"


def test_o_conflito_reporta_o_identificador_COMO_O_BANCO_ESCREVEU(db_session: Session):
    """Mostrar 'TED1' a quem tem '0ted-1' no arquivo transformaria o aviso em
    enigma — e o aviso existe justamente para o operador achar a linha."""
    _importar(db_session, _ofx(CONTA["completa"], "0ted-1", "20260810"))
    arquivo = _ofx(CONTA["completa"], "0ted-1", "20260810").replace(
        f"<TRNAMT>{VALOR}", "<TRNAMT>7777.00"
    )
    r = _importar(db_session, arquivo)
    assert r.conflitos == 1
    assert r.documentos_em_conflito == ("0ted-1",)
