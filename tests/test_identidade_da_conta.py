"""
A identidade da conta (migration 028), e o gate de cobrança na baixa (OC026).

POR QUE ESTE ARQUIVO EXISTE, e a razão importa mais que os testes: a migration
027 fechou três altos de cobrança e ABRIU UM CRÍTICO no mesmo commit, verificada
e verde. Ela pôs `conta_origem` — a GRAFIA que o arquivo trouxe — na chave única
do extrato, supondo que aquilo identificasse a conta. A verificação dela
perguntou "mesmo FITID em contas DIFERENTES entra?" e comemorou o sim; nunca
perguntou "e quando é a MESMA conta escrita de dois jeitos?".

O que este arquivo prova, então, não é só que a 028 funciona. É que as duas
direções foram testadas:

  1. a MESMA conta em grafias diferentes é UMA conta      (o conserto da 028)
  2. contas DIFERENTES continuam diferentes                (a conquista da 027)

Um teste que só cobre (1) reabre o furo da 027 na próxima refatoração; um que só
cobre (2) é o que deixou o crítico passar. Os dois juntos são o enunciado
inteiro.
"""

import hashlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.capital_engine import (
    ativar_operacao,
    baixar_parcela,
    importar_extrato_ofx,
    registrar_movimento_bancario,
)
from app.core.exceptions import BaixaForaDeCobranca
from app.ofx import conta_chave, ler_ofx
from tests.conftest import confirmar_registro, sqlstate_de


# ---------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------


def _ofx(bankid: str | None, acctid: str, transacoes: list[tuple[str, str, str]]) -> str:
    """Um OFX 1.x mínimo e VÁLIDO, com a conta escrita como o banco escreveria.

    `bankid=None` é o caso que quebrou a 027: a mesma conta, exportada sem o
    código do banco — coisa que acontece entre duas sessões do internet banking
    do mesmo cliente, sem ninguém agir de má-fé.
    """
    cabecalho = f"<BANKID>{bankid}\n" if bankid else ""
    linhas = "\n".join(
        f"<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>{data}<TRNAMT>{valor}"
        f"<FITID>{fitid}<NAME>TOMADOR</STMTTRN>"
        for fitid, data, valor in transacoes
    )
    return (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n\n"
        "<OFX>\n<BANKMSGSRSV1><STMTTRNRS><STMTRS>\n<CURDEF>BRL\n"
        f"<BANKACCTFROM>\n{cabecalho}<ACCTID>{acctid}\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n"
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


def _operacao_ativa(db_session: Session, tomador_id: uuid.UUID, parcelas: int = 4) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 0, 'PRICE', :n, 'registrada', 'REG-028')
        returning id
        """),
        {"t": str(tomador_id), "n": parcelas},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)
    return op_id


# ---------------------------------------------------------------------
# 1. A canonização, e o espelho entre Python e SQL
# ---------------------------------------------------------------------

CASOS_DE_CONTA = [
    # (grafia, chave esperada)
    ("001/123456", "123456"),
    ("123456", "123456"),  # a MESMA conta sem BANKID
    ("0001/123456", "123456"),  # zero à esquerda no banco
    ("001/0123456", "123456"),  # zero à esquerda na conta
    ("001/12345-6", "123456"),  # dígito verificador separado
    ("237/98765-4", "987654"),  # outra conta: continua outra
    ("001/abc123", "ABC123"),  # conta com letra
    ("000", None),  # só zeros não identifica nada
    ("---", None),  # só pontuação, idem
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("grafia,esperado", CASOS_DE_CONTA)
def test_conta_chave_canoniza(grafia, esperado):
    assert conta_chave(grafia) == esperado


def test_conta_chave_python_e_sql_concordam(db_session: Session):
    """A regra mora no BANCO (a coluna gerada usa `fn_conta_chave`) e a cópia em
    Python existe só para deduplicar dentro do arquivo, antes de qualquer INSERT.

    Duas implementações da mesma regra é dívida; o que a torna honesta é este
    teste. Sem ele, uma divergência sutil — `str.isalnum()` do Python aceita 'ç',
    o `[^0-9A-Za-z]` do Postgres não — faria a deduplicação em memória discordar
    da chave do banco em silêncio, que é exatamente a classe de defeito que a
    028 veio consertar.
    """
    for grafia, _ in CASOS_DE_CONTA:
        do_banco = db_session.execute(
            text("select fn_conta_chave(cast(:g as text))"), {"g": grafia}
        ).scalar_one()
        assert do_banco == conta_chave(grafia), f"divergiram para {grafia!r}"


def test_conta_chave_da_coluna_e_gerada_pelo_banco(db_session: Session):
    """A aplicação não escreve `conta_chave` — ela nem aparece no INSERT. Se um
    cliente pudesse enviá-la, poderia separar o que deveria unir, e a chave
    deixaria de ser função do dado gravado."""
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("""
            insert into movimento_bancario
                (data_movimento, valor, documento, origem, arquivo_sha256,
                 conta_origem, conta_chave)
            values (current_date, 100, 'FORJADO-1', 'ofx', :sha, '001/123456', 'OUTRA')
            """),
            {"sha": "a" * 64},
        )
    db_session.rollback()


# ---------------------------------------------------------------------
# 2. O crítico: a mesma conta em duas grafias é UMA conta
# ---------------------------------------------------------------------


def test_mesma_conta_em_duas_grafias_nao_dobra_o_lastro(db_session: Session):
    """O crítico que a 027 abriu, na forma exata em que foi reproduzido.

    Antes da 028 as duas importações CRIAVAM: R$ 31.514,86 recebidos viravam
    R$ 63.029,72 de lastro, as parcelas ficavam quitadas contra dinheiro que não
    entrou, `liquidar` era aceito (OC022 pede exatamente "todas as parcelas
    pagas") e o comprometido voltava a zero com principal na rua.
    """
    linhas = [("TED0001", "20260810", "15757.43"), ("TED0002", "20260910", "15757.43")]
    com_bankid = _ofx("001", "123456", linhas)
    sem_bankid = _ofx(None, "123456", linhas)

    primeira = _importar(db_session, com_bankid)
    assert primeira.criados == 2

    segunda = _importar(db_session, sem_bankid)
    assert segunda.criados == 0, "a mesma conta escrita de outro jeito criou lastro de novo"
    assert segunda.ja_registrados == 2
    assert segunda.conflitos == 0, "mesmo valor e mesma data: é reimportação, não anomalia"

    total = db_session.execute(
        text("select coalesce(sum(valor), 0) from movimento_bancario")
    ).scalar_one()
    assert Decimal(total) == Decimal("31514.86")


def test_a_aritmetica_do_relatorio_continua_fechando(db_session: Session):
    """A propriedade que torna o relatório auditável não pode ter sido perdida
    ao acrescentar o quinto destino."""
    arquivo = _ofx(
        "001",
        "123456",
        [
            ("A1", "20260810", "100.00"),
            ("A1", "20260810", "100.00"),  # repetido DENTRO do arquivo
            ("A2", "20260811", "-50.00"),  # débito
            ("A3", "20260812", "200.00"),
        ],
    )
    r = _importar(db_session, arquivo)
    assert (
        r.lidas
        == r.criados + r.ja_registrados + r.conflitos + r.repetidos_no_arquivo + r.debitos_ignorados
    )
    assert r.repetidos_no_arquivo == 1
    assert r.debitos_ignorados == 1


def test_duas_grafias_no_MESMO_arquivo_tambem_nao_dobram(db_session: Session):
    """Consertar só o banco deixaria isto de pé: a deduplicação em memória roda
    ANTES do INSERT e, se usasse a grafia, mandaria as duas linhas para o
    banco — onde a chave as recusaria, mas contadas como `ja_registrados` em vez
    de `repetidos_no_arquivo`. O conserto precisa ser dos dois lados."""
    arquivo = (
        _ofx("001", "123456", [("X1", "20260810", "500.00")]).replace("</OFX>\n", "")
        + _ofx(None, "123456", [("X1", "20260810", "500.00")]).split("<CURDEF>BRL\n", 1)[1]
    )
    r = _importar(db_session, arquivo)
    assert r.criados == 1
    assert r.repetidos_no_arquivo == 1


# ---------------------------------------------------------------------
# 3. A conquista da 027: contas DIFERENTES continuam diferentes
# ---------------------------------------------------------------------


def test_bancos_diferentes_com_o_mesmo_fitid_coexistem(db_session: Session):
    """O achado que a 027 fechou, e que a 028 não pode desfazer: FITID é único
    DENTRO da conta, e banco brasileiro emite sequência curta. Com a chave
    global da 009, o crédito do segundo banco era descartado como "já
    registrado" — a aritmética fechava enquanto a linha se perdia."""
    banco_a = _ofx("001", "111111", [("1", "20260810", "1000.00")])
    banco_b = _ofx("237", "222222", [("1", "20260810", "2000.00")])

    assert _importar(db_session, banco_a).criados == 1
    segunda = _importar(db_session, banco_b)
    assert segunda.criados == 1, "o crédito do segundo banco foi descartado"

    total = db_session.execute(
        text("select coalesce(sum(valor), 0) from movimento_bancario")
    ).scalar_one()
    assert Decimal(total) == Decimal("3000.00")


def test_manual_repetido_continua_recusado(db_session: Session):
    """O `NULLS NOT DISTINCT` da 027, preservado: dois lançamentos digitados com
    o mesmo documento têm `conta_origem` NULL, e `NULL = NULL` é NULL. Sem a
    cláusula, a idempotência do lançamento à mão desapareceria em silêncio."""
    registrar_movimento_bancario(
        db_session, data_movimento=date.today(), valor=Decimal("100"), documento="MANUAL-X"
    )
    from app.core.exceptions import MovimentoDuplicado

    with pytest.raises(MovimentoDuplicado):
        registrar_movimento_bancario(
            db_session, data_movimento=date.today(), valor=Decimal("100"), documento="MANUAL-X"
        )


# ---------------------------------------------------------------------
# 4. A colisão residual deixa de ser silenciosa
# ---------------------------------------------------------------------


def test_mesma_chave_com_valor_diferente_vira_conflito_e_nao_rotina(db_session: Session):
    """A 028 estreita a janela da colisão, não a fecha: dois bancos com o mesmo
    número de conta E o mesmo FITID ainda colidem. O que ela conserta é o
    SILÊNCIO — o achado da 027 nunca foi "uma linha se perdeu", foi "uma linha se
    perdeu E A ARITMÉTICA FECHOU"."""
    primeiro = _ofx("001", "123456", [("COLIDE", "20260810", "100.00")])
    assert _importar(db_session, primeiro).criados == 1

    # Mesmo FITID, mesma conta canônica, OUTRO valor: não é a mesma transação.
    segundo = _ofx("001", "123456", [("COLIDE", "20260810", "999.00")])
    r = _importar(db_session, segundo)

    assert r.criados == 0
    assert r.conflitos == 1, "colisão de identidade contada como reimportação de rotina"
    assert r.ja_registrados == 0, "conflito não pode somar duas vezes: a aritmética quebraria"
    assert r.documentos_em_conflito == ("COLIDE",)
    assert r.lidas == r.criados + r.ja_registrados + r.conflitos + r.repetidos_no_arquivo


def test_data_diferente_tambem_e_conflito(db_session: Session):
    assert _importar(db_session, _ofx("001", "123456", [("D1", "20260810", "100.00")])).criados == 1
    r = _importar(db_session, _ofx("001", "123456", [("D1", "20260915", "100.00")]))
    assert r.conflitos == 1


# ---------------------------------------------------------------------
# 5. OC026 — a baixa exige operação em cobrança
# ---------------------------------------------------------------------


def _novar_e_ativar(db_session: Session, op_id: uuid.UUID) -> uuid.UUID:
    """Renegociação legítima: mesmo valor, prazo maior. A original vira
    'renegociada' quando a substituta é ATIVADA (migration 026)."""
    substituta = db_session.execute(
        text("select fn_novar_operacao(:op, 12000, 0, 'PRICE', 8, 'REG-NOVA')"),
        {"op": str(op_id)},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, substituta)
    ativar_operacao(db_session, substituta)
    return substituta


def test_agenda_de_titulo_renegociado_nao_recebe_baixa(
    db_session: Session, tomador_autorizado, capital_constituido
):
    """O alto que a 028 fecha, medido pela porta de produção antes dela: 204 no
    endpoint, parcela 'paga' numa operação 'renegociada', movimento consumido
    PARA SEMPRE (não há estorno) e a parcela VIVA da substituta passando a ser
    recusada com OC011 "movimento já usado"."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    _novar_e_ativar(db_session, op_id)

    status = db_session.execute(
        text("select status from operacao_credito where id = :op"), {"op": str(op_id)}
    ).scalar_one()
    assert status == "renegociada"

    orfa = db_session.execute(
        text("select id from parcela where operacao_id = :op and numero = 1"),
        {"op": str(op_id)},
    ).scalar_one()
    movimento = registrar_movimento_bancario(
        db_session, data_movimento=date.today(), valor=Decimal("99999"), documento="TED-ORFA"
    )

    with pytest.raises(BaixaForaDeCobranca):
        baixar_parcela(db_session, orfa, movimento)


def test_update_direto_na_agenda_extinta_tambem_e_recusado(
    db_session: Session, tomador_autorizado, capital_constituido
):
    """Pela mesma razão da 027: `fn_baixar_parcela` é o único caminho pela
    APLICAÇÃO, não o único caminho pelo banco."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    _novar_e_ativar(db_session, op_id)

    orfa = db_session.execute(
        text("select id from parcela where operacao_id = :op and numero = 1"),
        {"op": str(op_id)},
    ).scalar_one()
    movimento = registrar_movimento_bancario(
        db_session, data_movimento=date.today(), valor=Decimal("99999"), documento="TED-ORFA-2"
    )

    with pytest.raises(DBAPIError) as excinfo:
        db_session.execute(
            text("update parcela set status='paga', movimento_id=:m where id=:p"),
            {"m": str(movimento), "p": str(orfa)},
        )
    db_session.rollback()
    assert sqlstate_de(excinfo.value) == "OC026"


def test_a_agenda_VIVA_da_substituta_continua_recebendo_baixa(
    db_session: Session, tomador_autorizado, capital_constituido
):
    """A guarda tem que barrar o título extinto e deixar passar o vivo. Uma
    guarda que recusa o caminho legítimo é tão defeito quanto a que deixa passar
    o ilegítimo."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    substituta = _novar_e_ativar(db_session, op_id)

    viva = db_session.execute(
        text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
        {"op": str(substituta)},
    ).one()
    movimento = registrar_movimento_bancario(
        db_session,
        data_movimento=date.today(),
        valor=Decimal(viva.valor_total),
        documento="TED-VIVA",
    )
    baixar_parcela(db_session, viva.id, movimento)

    status = db_session.execute(
        text("select status from parcela where id = :p"), {"p": str(viva.id)}
    ).scalar_one()
    assert status == "paga"


# ---------------------------------------------------------------------
# 6. As três tabelas append-only que ficaram de fora do TRUNCATE
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "tabela,sqlstate",
    [
        ("contrato_emprestimo", "OC017"),
        ("registro_operacao", "OC018"),
        ("apuracao_fiscal", "OC016"),
    ],
)
def test_truncate_recusado_nas_tres_tabelas_que_faltavam(
    db_session: Session, tabela: str, sqlstate: str
):
    """A 016 cobriu cinco tabelas, a 027 acrescentou `parcela`, e estas três
    ficaram de fora — declaradas imutáveis por trigger de LINHA, que TRUNCATE
    atravessa porque não visita linha nenhuma."""
    with pytest.raises(DBAPIError) as excinfo:
        db_session.execute(text(f"truncate table {tabela} cascade"))
    db_session.rollback()
    assert sqlstate_de(excinfo.value) == sqlstate
