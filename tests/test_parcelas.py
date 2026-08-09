"""
Agenda de parcelas (migration 007) contra Postgres real.

Duas coisas estão sob teste aqui, e a segunda importa tanto quanto a
primeira: que a matemática de PRICE e SAC feche EXATAMENTE (sem centavo
sobrando), e que a agenda seja imutável depois de emitida.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, novar_operacao, transicionar_operacao
from tests.conftest import baixar_parcelas, confirmar_registro, sqlstate_de


def _criar(
    db_session: Session,
    tomador_id: uuid.UUID,
    valor: str,
    taxa: str = "2.5",
    sistema: str = "PRICE",
    parcelas: int = 12,
) -> uuid.UUID:
    result = db_session.execute(
        text(
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values (:t, 'emprestimo', :v, :taxa, :sis, :n, 'registrada', 'REG-TEST')
            returning id
            """
        ),
        {"t": str(tomador_id), "v": valor, "taxa": taxa, "sis": sistema, "n": parcelas},
    )
    db_session.commit()
    op_id = result.scalar_one()
    confirmar_registro(db_session, op_id)
    return op_id


def _agenda(db_session: Session, op_id: uuid.UUID) -> list:
    return db_session.execute(
        text("""
        select numero, vencimento, valor_amortizacao, valor_juros,
               valor_total, saldo_devedor_pos, status
        from parcela where operacao_id = :id order by numero
        """),
        {"id": str(op_id)},
    ).all()


# ---------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------


def test_ativacao_gera_agenda_completa(db_session, tomador_autorizado, capital_constituido):
    """Não existe operação ativa sem agenda: o trigger roda na mesma transação."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert len(agenda) == 12
    assert [p.numero for p in agenda] == list(range(1, 13))
    assert all(p.status == "aberta" for p in agenda)


def test_operacao_nao_ativada_nao_tem_agenda(db_session, tomador_autorizado, capital_constituido):
    """A agenda é emitida na ativação, não na criação — antes disso não há
    o que cobrar nem data a partir da qual contar vencimentos."""
    op_id = _criar(db_session, tomador_autorizado, "12000")
    assert _agenda(db_session, op_id) == []


def test_price_amortizacao_fecha_exatamente(db_session, tomador_autorizado, capital_constituido):
    """A soma das amortizações é EXATAMENTE o principal e o saldo devedor
    final é 0,00. Se sobrar centavo, a quitação nunca fecha."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="2.5", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("12000.00")
    assert agenda[-1].saldo_devedor_pos == Decimal("0.00")


def test_price_prestacao_constante(db_session, tomador_autorizado, capital_constituido):
    """Característica que define o PRICE: a prestação não muda. A última é
    a única que pode divergir, por absorver o resíduo de arredondamento."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="2.5", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    totais = {p.valor_total for p in agenda[:-1]}
    assert len(totais) == 1, f"prestação PRICE deveria ser constante, veio {totais}"

    # E os juros decrescem, porque incidem sobre saldo devedor que cai.
    juros = [p.valor_juros for p in agenda]
    assert juros == sorted(juros, reverse=True)


def test_sac_amortizacao_constante_e_parcela_decrescente(
    db_session, tomador_autorizado, capital_constituido
):
    """Característica que define o SAC: amortização fixa, prestação caindo."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="2.5", sistema="SAC", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    amortizacoes = {p.valor_amortizacao for p in agenda}
    assert len(amortizacoes) == 1  # 12000/12 = 1000, divisão exata, nem a última diverge
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("12000.00")

    totais = [p.valor_total for p in agenda]
    assert totais == sorted(totais, reverse=True)
    assert totais[0] > totais[-1]


def test_sac_com_divisao_inexata_ainda_fecha(db_session, tomador_autorizado, capital_constituido):
    """10.000 em 3 parcelas dá 3.333,33... — o resíduo tem que ir para a
    última, senão faltam centavos no total."""
    op_id = _criar(db_session, tomador_autorizado, "10000", sistema="SAC", parcelas=3)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("10000.00")
    assert agenda[-1].saldo_devedor_pos == Decimal("0.00")
    assert agenda[-1].valor_amortizacao == Decimal("3333.34")


def test_taxa_zero_nao_quebra_a_ativacao(db_session, tomador_autorizado, capital_constituido):
    """Com i = 0 o denominador do PRICE (1 - (1+i)^-n) vira zero. Sem o
    desvio explícito, uma operação sem juros — válida — derrubaria a
    ativação com division_by_zero."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="0", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert len(agenda) == 12
    assert all(p.valor_juros == Decimal("0.00") for p in agenda)
    assert all(p.valor_total == Decimal("1000.00") for p in agenda)
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("12000.00")


def test_vencimentos_mensais_crescentes(db_session, tomador_autorizado, capital_constituido):
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=6)
    ativar_operacao(db_session, op_id)

    vencimentos = [p.vencimento for p in _agenda(db_session, op_id)]
    assert vencimentos == sorted(vencimentos)
    assert len(set(vencimentos)) == 6


# ---------------------------------------------------------------------
# Idempotência
# ---------------------------------------------------------------------


def test_reativar_inadimplente_nao_regenera_agenda(
    db_session, tomador_autorizado, capital_constituido
):
    """Regenerar a agenda ao reativar reescreveria vencimentos já vencidos
    com datas novas — apagaria justamente a prova da inadimplência."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)
    original = _agenda(db_session, op_id)

    transicionar_operacao(db_session, op_id, "inadimplente")
    ativar_operacao(db_session, op_id)

    depois = _agenda(db_session, op_id)
    assert len(depois) == 12
    assert [p.vencimento for p in depois] == [p.vencimento for p in original]
    assert [p.valor_total for p in depois] == [p.valor_total for p in original]


def test_novacao_gera_agenda_propria_para_a_substituta(
    db_session, tomador_autorizado, capital_constituido
):
    """A substituta é outra operação, com outras condições: ativá-la emite
    a agenda dela, e a da original permanece intacta como histórico."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    nova = novar_operacao(
        db_session,
        op_id,
        valor_principal=Decimal("8000"),
        taxa_juros_mensal=Decimal("1.5"),
        sistema_amortizacao="SAC",
        numero_parcelas=8,
        registro_entidade_ref="REG-NOVA",
    )
    # A substituta é OUTRA operação: precisa do próprio registro confirmado.
    # É a leitura correta da lei — a novação cria um novo título, e o novo
    # título tem que ser registrado.
    confirmar_registro(db_session, nova.id)
    ativar_operacao(db_session, nova.id)

    assert len(_agenda(db_session, op_id)) == 12  # original preservada
    agenda_nova = _agenda(db_session, nova.id)
    assert len(agenda_nova) == 8
    assert sum(p.valor_amortizacao for p in agenda_nova) == Decimal("8000.00")


# ---------------------------------------------------------------------
# Imutabilidade (OC009)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("valor_total", "1.00"),
        ("valor_juros", "0.00"),
        ("valor_amortizacao", "9999.00"),
        ("vencimento", "2030-01-01"),
        ("numero", "99"),
        ("saldo_devedor_pos", "0.00"),
    ],
)
def test_alterar_parcela_emitida_e_recusado(
    db_session, tomador_autorizado, capital_constituido, campo, valor
):
    """Nenhum valor nem data da agenda muda depois de emitida. Se mudasse,
    a cobrança deixaria de ser defensável — não haveria como provar o que
    foi acordado na ativação."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text(f"update parcela set {campo} = :v where operacao_id = :id and numero = 1"),
            {"v": valor, "id": str(op_id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC009"
    db_session.rollback()


def test_apagar_parcela_emitida_e_recusado(db_session, tomador_autorizado, capital_constituido):
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        db_session.execute(text("delete from parcela where operacao_id = :id"), {"id": str(op_id)})
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC009"
    db_session.rollback()


def test_baixa_de_recebimento_e_permitida(db_session, tomador_autorizado, capital_constituido):
    """status e pago_em são a exceção deliberada à imutabilidade: é por eles
    que a baixa acontece, sem tocar nos valores acordados. Desde a migration
    009 a baixa exige lastro bancário — daí passar por `fn_baixar_parcela`."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    baixar_parcelas(db_session, op_id, [1])

    agenda = _agenda(db_session, op_id)
    assert agenda[0].status == "paga"
    assert agenda[1].status == "aberta"
