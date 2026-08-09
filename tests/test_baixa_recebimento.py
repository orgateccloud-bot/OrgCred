"""
Baixa de recebimento amarrada a movimentação bancária (migration 009).

O invariante central: não existe parcela paga sem linha de extrato. Se
existisse, bastaria um UPDATE para fazer a régua de inadimplência (008)
parar de ver o atraso de uma dívida que continua em aberto — uma carteira
podre passaria por saudável sem que nada no sistema registrasse a mentira.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, baixar_parcela, registrar_movimento_bancario
from app.core.exceptions import BaixaInvalida
from tests.conftest import confirmar_registro, sqlstate_de


def _operacao_ativa(db_session: Session, tomador_id: uuid.UUID, parcelas: int = 12) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 0, 'PRICE', :n, 'registrada', 'REG-BAIXA')
        returning id
        """),
        {"t": str(tomador_id), "n": parcelas},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)
    return op_id


def _parcela(db_session: Session, op_id: uuid.UUID, numero: int):
    return db_session.execute(
        text("""
        select id, valor_total, status, movimento_id
        from parcela where operacao_id = :op and numero = :n
        """),
        {"op": str(op_id), "n": numero},
    ).one()


def _movimento(db_session: Session, valor: str, documento: str | None = None) -> uuid.UUID:
    return registrar_movimento_bancario(
        db_session,
        data_movimento=date.today(),
        valor=Decimal(valor),
        documento=documento or f"DOC-{uuid.uuid4().hex[:12]}",
    )


# ---------------------------------------------------------------------
# Caminho feliz
# ---------------------------------------------------------------------


def test_baixa_amarra_parcela_ao_movimento(db_session, tomador_autorizado, capital_constituido):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    mov = _movimento(db_session, str(p.valor_total))

    baixar_parcela(db_session, p.id, mov)

    depois = _parcela(db_session, op_id, 1)
    assert depois.status == "paga"
    assert depois.movimento_id == mov


def test_movimento_maior_cobre_a_parcela(db_session, tomador_autorizado, capital_constituido):
    """Juros de mora fazem o tomador pagar MAIS que o valor original. Exigir
    igualdade impediria a baixa de todo pagamento atrasado — justamente os
    que mais importam para a cobrança."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)

    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total + Decimal("50"))))

    assert _parcela(db_session, op_id, 1).status == "paga"


def test_baixa_tira_a_parcela_do_aging(db_session, tomador_autorizado, capital_constituido):
    """Fecha o ciclo da Frente 3: é a baixa com lastro — e só ela — que faz
    a operação sair do atraso."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)

    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    db_session.execute(
        text(
            "update parcela set vencimento = current_date - 60 where operacao_id = :id and numero = 1"
        ),
        {"id": str(op_id)},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()

    assert (
        db_session.execute(text("select fn_dias_atraso(:id)"), {"id": str(op_id)}).scalar_one()
        == 60
    )

    p = _parcela(db_session, op_id, 1)
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    assert (
        db_session.execute(text("select fn_dias_atraso(:id)"), {"id": str(op_id)}).scalar_one() == 0
    )


# ---------------------------------------------------------------------
# O invariante: não há paga sem lastro
# ---------------------------------------------------------------------


def test_marcar_paga_direto_no_banco_e_recusado(
    db_session, tomador_autorizado, capital_constituido
):
    """A garantia é do trigger, não da aplicação: nem por SQL direto se dá
    uma parcela por paga sem movimento bancário."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set status = 'paga' where operacao_id = :id and numero = 1"),
            {"id": str(op_id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()


def test_movimento_nao_pode_baixar_duas_parcelas(
    db_session, tomador_autorizado, capital_constituido
):
    """Sem esta trava, um único crédito de R$ 1.000 no extrato baixaria dez
    parcelas — a carteira inteira ficaria "paga" com o dinheiro de uma."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p1 = _parcela(db_session, op_id, 1)
    p2 = _parcela(db_session, op_id, 2)
    mov = _movimento(db_session, "99999")

    baixar_parcela(db_session, p1.id, mov)

    with pytest.raises(BaixaInvalida, match="já foi usado"):
        baixar_parcela(db_session, p2.id, mov)
    assert _parcela(db_session, op_id, 2).status == "aberta"


def test_movimento_menor_que_a_parcela_e_recusado(
    db_session, tomador_autorizado, capital_constituido
):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)

    with pytest.raises(BaixaInvalida, match="não cobre a parcela"):
        baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total - Decimal("1"))))


def test_parcela_ja_baixada_nao_aceita_nova_baixa(
    db_session, tomador_autorizado, capital_constituido
):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    with pytest.raises(BaixaInvalida, match="não está em aberto"):
        baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))


def test_baixa_e_terminal(db_session, tomador_autorizado, capital_constituido):
    """Voltar uma parcela paga para aberta apagaria o lastro em silêncio.
    Não há estorno definido — a correção se faz no extrato (ver 009)."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set status = 'aberta' where id = :id"), {"id": str(p.id)}
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()


def test_parcela_ou_movimento_inexistente(db_session, tomador_autorizado, capital_constituido):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)

    with pytest.raises(BaixaInvalida, match="não existe"):
        baixar_parcela(db_session, uuid.uuid4(), _movimento(db_session, "9999"))

    with pytest.raises(BaixaInvalida, match="não existe"):
        baixar_parcela(db_session, p.id, uuid.uuid4())


# ---------------------------------------------------------------------
# Movimento bancário
# ---------------------------------------------------------------------


def test_documento_duplicado_e_recusado(db_session):
    """Idempotência da importação: reimportar o mesmo extrato — rotina na
    operação real — não pode duplicar crédito."""
    _movimento(db_session, "1000", documento="FITID-123")

    with pytest.raises(BaixaInvalida, match="Já existe um movimento"):
        _movimento(db_session, "1000", documento="FITID-123")


def test_movimento_e_imutavel(db_session):
    """Extrato é fato de fora: quem corrige é o banco, com outro lançamento."""
    mov = _movimento(db_session, "1000")

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update movimento_bancario set valor = 1 where id = :id"), {"id": str(mov)}
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC012"
    db_session.rollback()


def test_movimento_conciliado_sai_dos_disponiveis(
    db_session, tomador_autorizado, capital_constituido
):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    mov = _movimento(db_session, str(p.valor_total))

    assert (
        db_session.execute(
            text("select count(*) from v_movimentos_disponiveis where id = :id"), {"id": str(mov)}
        ).scalar_one()
        == 1
    )

    baixar_parcela(db_session, p.id, mov)

    assert (
        db_session.execute(
            text("select count(*) from v_movimentos_disponiveis where id = :id"), {"id": str(mov)}
        ).scalar_one()
        == 0
    )
