"""
O instrumento vigente não se fabrica por salto de versão (migration 033).

Um INSERT direto de versão alta (99) em contrato_emprestimo ou apuracao_fiscal
virava a linha VIGENTE — as views servem a maior versão, e a imutabilidade da
016/017/018 só guardava UPDATE/DELETE. Mesma classe do apêndice de parcela que
a 027 fechou.

O que a 033 fecha: a MONOTONIA de versão (só a próxima entra), que mata o salto.
O que ela NÃO fecha, e é decisão registrada no cabeçalho do .sql: uma forja na
PRÓXIMA versão por SQL direto (§7, a app é dona da tabela) e uma apuração com
números inconsistentes (já DENUNCIADA pela memória de cálculo — acoplar a
fórmula a um CHECK quebraria a evolução de fórmula que a memória existe para
cobrir).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.conftest import sqlstate_de


def _operacao_com_contrato(db_session: Session) -> uuid.UUID:
    tid = db_session.execute(
        text("""
        insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
        values (:c, 'Real', 'ME', 'Sao Paulo', 'SP', true) returning id
        """),
        {"c": uuid.uuid4().int.__str__()[:14]},
    ).scalar_one()
    op = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status)
        values (:t, 'emprestimo', 12000, 2, 'PRICE', 4, 'registrada') returning id
        """),
        {"t": str(tid)},
    ).scalar_one()
    db_session.execute(
        text("""
        insert into contrato_emprestimo (operacao_id, versao, corpo, sha256)
        values (:o, 1, 'CONTRATO LEGITIMO', :h)
        """),
        {"o": str(op), "h": "a" * 64},
    )
    db_session.commit()
    return op


def test_contrato_com_versao_alta_e_recusado(db_session: Session) -> None:
    op = _operacao_com_contrato(db_session)
    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text("""
            insert into contrato_emprestimo (operacao_id, versao, corpo, sha256)
            values (:o, 99, 'CONTRATO FORJADO: divida perdoada', :h)
            """),
            {"o": str(op), "h": "f" * 64},
        )
    db_session.rollback()
    assert sqlstate_de(exc.value) == "OC017"


def test_contrato_reemissao_na_proxima_versao_passa(db_session: Session) -> None:
    """A monotonia não pode barrar o fluxo legítimo — a reemissão insere max+1."""
    op = _operacao_com_contrato(db_session)
    db_session.execute(
        text("""
        insert into contrato_emprestimo (operacao_id, versao, corpo, sha256)
        values (:o, 2, 'CONTRATO REEMITIDO', :h)
        """),
        {"o": str(op), "h": "b" * 64},
    )
    db_session.commit()
    vigente = db_session.execute(
        text(
            "select versao from contrato_emprestimo where operacao_id = :o order by versao desc limit 1"
        ),
        {"o": str(op)},
    ).scalar_one()
    assert vigente == 2


def test_apuracao_com_versao_alta_e_recusada(db_session: Session) -> None:
    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text("""
            insert into apuracao_fiscal
                (ano, trimestre, versao, receita_juros, receita_demais,
                 base_irpj, irpj, adicional_irpj, base_csll, csll, pis, cofins, total_tributos,
                 percentual_presuncao_irpj, percentual_presuncao_csll, aliquota_irpj, aliquota_csll,
                 adicional_irpj_aliquota, adicional_irpj_limite, aliquota_pis, aliquota_cofins,
                 regime_reconhecimento)
            values
                (2026, 1, 99, 888888, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                 0.32, 0.32, 0.15, 0.09, 0.10, 60000, 0.0065, 0.03, 'caixa')
            """)
        )
    db_session.rollback()
    assert sqlstate_de(exc.value) == "OC016"


def test_apuracao_na_primeira_versao_passa(db_session: Session) -> None:
    """Uma apuração torta na versão CERTA ainda entra — de propósito: é a memória
    de cálculo que a denuncia (confere=false), e é o cenário de fórmula que
    evoluiu (a 018 mudou a 011). A 033 não acopla o banco à fórmula. Este teste
    fixa essa fronteira: monotonia sim, aritmética não."""
    db_session.execute(
        text("""
        insert into apuracao_fiscal
            (ano, trimestre, versao, receita_juros, receita_demais,
             base_irpj, irpj, adicional_irpj, base_csll, csll, pis, cofins, total_tributos,
             percentual_presuncao_irpj, percentual_presuncao_csll, aliquota_irpj, aliquota_csll,
             adicional_irpj_aliquota, adicional_irpj_limite, aliquota_pis, aliquota_cofins,
             regime_reconhecimento)
        values
            (2099, 4, 1, 1000, 0, 320, 999.99, 0, 320, 28.80, 6.50, 30.00, 1065.29,
             0.32, 0.32, 0.15, 0.09, 0.10, 60000, 0.0065, 0.03, 'competencia')
        """)
    )
    db_session.commit()
    v = db_session.execute(
        text("select irpj from apuracao_fiscal where ano=2099 and trimestre=4")
    ).scalar_one()
    assert v == Decimal("999.99")
