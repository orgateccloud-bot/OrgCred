"""
Aging de inadimplência e trilha de autoria (migration 008) contra Postgres real.

O que importa provar aqui, em ordem de gravidade:
1. Que a régua automática NÃO reativa sozinha (só marca inadimplência).
2. Que um ato do sistema nunca é imputado a uma pessoa, e vice-versa.
3. Que a trilha é append-only.
4. Que o aging é derivado da agenda, e não de coluna que alguém atualiza.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, processar_aging, transicionar_operacao
from tests.conftest import baixar_parcelas, sqlstate_de


def _criar_ativa(
    db_session: Session,
    tomador_id: uuid.UUID,
    valor: str = "12000",
    parcelas: int = 12,
    usuario_id: str | None = None,
) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', :v, 2.5, 'PRICE', :n, 'registrada', 'REG-AGING')
        returning id
        """),
        {"t": str(tomador_id), "v": valor, "n": parcelas},
    ).scalar_one()
    db_session.commit()
    ativar_operacao(db_session, op_id, usuario_id=usuario_id)
    return op_id


def _envelhecer(db_session: Session, op_id: uuid.UUID, dias: int, quantas: int = 1) -> None:
    """Puxa os vencimentos das primeiras parcelas para o passado.

    Vencimento é imutável (OC009), então não dá para simplesmente atualizar:
    o teste desabilita o trigger de imutabilidade só neste ponto, para
    fabricar o cenário. Fazer isso pela API seria impossível — que é
    exatamente a garantia que a 007 introduziu.
    """
    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    db_session.execute(
        text("""
        update parcela set vencimento = :venc
        where operacao_id = :id and numero <= :quantas
        """),
        {"venc": date.today() - timedelta(days=dias), "id": str(op_id), "quantas": quantas},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()


def _eventos(db_session: Session, op_id: uuid.UUID) -> list:
    return db_session.execute(
        text("""
        select status_anterior, status_novo, origem, usuario_id, dias_atraso
        from operacao_evento where operacao_id = :id order by created_at
        """),
        {"id": str(op_id)},
    ).all()


# ---------------------------------------------------------------------
# Aging derivado da agenda
# ---------------------------------------------------------------------


def test_operacao_em_dia_tem_zero_dias_de_atraso(
    db_session, tomador_autorizado, capital_constituido
):
    """A agenda nasce com o primeiro vencimento no futuro."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    dias = db_session.execute(text("select fn_dias_atraso(:id)"), {"id": str(op_id)}).scalar_one()
    assert dias == 0


def test_dias_atraso_vem_da_parcela_vencida_mais_antiga(
    db_session, tomador_autorizado, capital_constituido
):
    op_id = _criar_ativa(db_session, tomador_autorizado)
    _envelhecer(db_session, op_id, dias=45, quantas=2)

    row = db_session.execute(
        text(
            "select dias_atraso, faixa, parcelas_vencidas from v_aging_operacoes where operacao_id = :id"
        ),
        {"id": str(op_id)},
    ).one()
    assert row.dias_atraso == 45
    assert row.faixa == "de_31_a_60"
    assert row.parcelas_vencidas == 2


def test_parcela_paga_sai_do_atraso(db_session, tomador_autorizado, capital_constituido):
    """O aging olha só parcelas em aberto — a baixa de recebimento é o que
    tira a operação do atraso, e é por `status` que ela acontece."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    _envelhecer(db_session, op_id, dias=45, quantas=1)

    baixar_parcelas(db_session, op_id, [1])

    dias = db_session.execute(text("select fn_dias_atraso(:id)"), {"id": str(op_id)}).scalar_one()
    assert dias == 0


@pytest.mark.parametrize(
    "dias,faixa",
    [
        (0, "em_dia"),
        (1, "ate_30"),
        (30, "ate_30"),
        (31, "de_31_a_60"),
        (61, "de_61_a_90"),
        (91, "acima_de_90"),
    ],
)
def test_faixas_de_aging(db_session, dias, faixa):
    assert db_session.execute(text("select fn_faixa_aging(:d)"), {"d": dias}).scalar_one() == faixa


def test_aging_ignora_operacoes_que_nao_comprometem_capital(
    db_session, tomador_autorizado, capital_constituido
):
    """Proposta e registrada não têm agenda; liquidada não tem o que cobrar."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    transicionar_operacao(db_session, op_id, "liquidada")

    assert (
        db_session.execute(
            text("select count(*) from v_aging_operacoes where operacao_id = :id"),
            {"id": str(op_id)},
        ).scalar_one()
        == 0
    )


# ---------------------------------------------------------------------
# Régua automática
# ---------------------------------------------------------------------


def test_regua_transiciona_apenas_acima_do_limite(
    db_session, tomador_autorizado, capital_constituido
):
    atrasada = _criar_ativa(db_session, tomador_autorizado, valor="10000")
    recente = _criar_ativa(db_session, tomador_autorizado, valor="10000")
    _envelhecer(db_session, atrasada, dias=100)
    _envelhecer(db_session, recente, dias=45)

    assert processar_aging(db_session, limite_dias=90) == 1

    status = dict(
        db_session.execute(
            text("select id::text, status from operacao_credito where id in (:a, :b)"),
            {"a": str(atrasada), "b": str(recente)},
        ).all()
    )
    assert status[str(atrasada)] == "inadimplente"
    assert status[str(recente)] == "ativa"


def test_regua_e_idempotente(db_session, tomador_autorizado, capital_constituido):
    """Rodar de novo no mesmo dia não deve gerar transição nem evento novo —
    senão o painel de auditoria encheria de ruído a cada execução."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    _envelhecer(db_session, op_id, dias=100)

    assert processar_aging(db_session, limite_dias=90) == 1
    eventos_apos_primeira = len(_eventos(db_session, op_id))

    assert processar_aging(db_session, limite_dias=90) == 0
    assert len(_eventos(db_session, op_id)) == eventos_apos_primeira


def test_regua_nunca_reativa_sozinha(db_session, tomador_autorizado, capital_constituido):
    """Mesmo com todas as parcelas pagas, a régua não devolve a operação
    para 'ativa': confirmar que o dinheiro entrou é decisão de uma pessoa,
    com nome na trilha."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    _envelhecer(db_session, op_id, dias=100)
    processar_aging(db_session, limite_dias=90)

    baixar_parcelas(db_session, op_id, list(range(1, 13)))

    assert processar_aging(db_session, limite_dias=90) == 0
    status = db_session.execute(
        text("select status from operacao_credito where id = :id"), {"id": str(op_id)}
    ).scalar_one()
    assert status == "inadimplente"


def test_inadimplente_continua_comprometendo_capital_apos_a_regua(
    db_session, tomador_autorizado, capital_constituido
):
    """Amarra a régua ao invariante da 006: transicionar automaticamente não
    pode virar uma porta dos fundos para liberar o teto do Art. 5º."""
    op_id = _criar_ativa(db_session, tomador_autorizado, valor="40000")
    _envelhecer(db_session, op_id, dias=100)

    processar_aging(db_session, limite_dias=90)

    comprometido = db_session.execute(
        text("""
        select coalesce(sum(valor_principal), 0) from operacao_credito
        where status in ('ativa', 'inadimplente')
        """)
    ).scalar_one()
    assert comprometido == Decimal("40000.00")


# ---------------------------------------------------------------------
# Trilha de autoria
# ---------------------------------------------------------------------


def test_transicao_da_regua_nao_tem_autor(db_session, tomador_autorizado, capital_constituido):
    """O que a régua fez não pode ser imputado a ninguém."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    _envelhecer(db_session, op_id, dias=100)
    processar_aging(db_session, limite_dias=90)

    evento = _eventos(db_session, op_id)[-1]
    assert (evento.status_anterior, evento.status_novo) == ("ativa", "inadimplente")
    assert evento.origem == "sistema"
    assert evento.usuario_id is None
    assert evento.dias_atraso >= 100


def test_transicao_humana_registra_o_autor(db_session, tomador_autorizado, capital_constituido):
    autor = str(uuid.uuid4())
    op_id = _criar_ativa(db_session, tomador_autorizado, usuario_id=autor)
    transicionar_operacao(db_session, op_id, "inadimplente", usuario_id=autor)

    evento = _eventos(db_session, op_id)[-1]
    assert evento.origem == "usuario"
    assert evento.usuario_id == autor


def test_origem_sistema_nao_sobrevive_a_transicao_seguinte(
    db_session, tomador_autorizado, capital_constituido
):
    """`app.origem` é setting de transação; se a régua não o limpasse, o ato
    humano seguinte na MESMA transação seria gravado como se o sistema o
    tivesse praticado — e ninguém responderia por ele."""
    autor = str(uuid.uuid4())
    op_id = _criar_ativa(db_session, tomador_autorizado)
    _envelhecer(db_session, op_id, dias=100)
    processar_aging(db_session, limite_dias=90)

    # Regularização logo em seguida, por uma pessoa.
    ativar_operacao(db_session, op_id, usuario_id=autor)

    evento = _eventos(db_session, op_id)[-1]
    assert (evento.status_anterior, evento.status_novo) == ("inadimplente", "ativa")
    assert evento.origem == "usuario"
    assert evento.usuario_id == autor


def test_criacao_e_registrada_na_trilha(db_session, tomador_autorizado, capital_constituido):
    """A trilha cobre o ciclo inteiro, não só a inadimplência."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    eventos = _eventos(db_session, op_id)
    assert [(e.status_anterior, e.status_novo) for e in eventos] == [
        (None, "registrada"),
        ("registrada", "ativa"),
    ]


def test_update_sem_mudanca_de_status_nao_gera_evento(
    db_session, tomador_autorizado, capital_constituido
):
    """Editar a referência do registro não é transição de estado."""
    op_id = _criar_ativa(db_session, tomador_autorizado)
    antes = len(_eventos(db_session, op_id))

    db_session.execute(
        text("update operacao_credito set registro_entidade_ref = 'OUTRO' where id = :id"),
        {"id": str(op_id)},
    )
    db_session.commit()

    assert len(_eventos(db_session, op_id)) == antes


def test_banco_nao_aceita_ato_do_sistema_com_autor(
    db_session, tomador_autorizado, capital_constituido
):
    """A garantia é da CHECK constraint, não da aplicação: nem inserindo
    direto no banco dá para atribuir a alguém um ato automático."""
    op_id = _criar_ativa(db_session, tomador_autorizado)

    with pytest.raises(Exception):
        db_session.execute(
            text("""
            insert into operacao_evento (operacao_id, status_novo, origem, usuario_id)
            values (:id, 'inadimplente', 'sistema', 'alguem')
            """),
            {"id": str(op_id)},
        )
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize(
    "comando", ["update operacao_evento set origem = 'usuario'", "delete from operacao_evento"]
)
def test_trilha_e_append_only(db_session, tomador_autorizado, capital_constituido, comando):
    _criar_ativa(db_session, tomador_autorizado)

    with pytest.raises(Exception) as exc:
        db_session.execute(text(comando))
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC010"
    db_session.rollback()
