"""
Suite da renegociação (novação atômica) e do capital comprometido coerente
— migration 006 + app.capital_engine. Prova os invariantes que fecham a
REVISAO_2026-07-11 item 3 ("Fluxo de renegociação indefinido") e os furos
G1/G2 (inadimplente liberava capital; renegociada saía sem evento no
ledger):

  1. Novação nunca conta capital em dobro em nenhum estado commitado.
  2. Novação é atômica: se a nova operação não couber no teto, NADA muda.
  3. 'inadimplente' continua comprometendo o teto (interpretação
     conservadora do Art. 5º).
  4. Toda saída do conjunto comprometido gera evento no ledger, e a
     cadeia de hash permanece íntegra mesmo com dois eventos na mesma
     transação (correção do desempate por seq).
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import (
    TermosRenegociacao,
    ativar_operacao,
    consultar_capital_disponivel,
    liquidar_operacao,
    marcar_inadimplente,
    regularizar_operacao,
    renegociar_operacao,
)
from app.core.exceptions import (
    OperacaoNaoEncontrada,
    TetoCapitalExcedido,
    TransicaoInvalida,
)
from tests.conftest import sqlstate_de
from tests.test_capital_engine import _criar_e_ativar_operacao_direto, _criar_operacao


def _termos(valor: int, registro_ref: str = "REG-NOVACAO") -> TermosRenegociacao:
    return TermosRenegociacao(
        valor_principal=valor,  # type: ignore[arg-type]
        taxa_juros_mensal=3,  # type: ignore[arg-type]
        numero_parcelas=24,
        sistema_amortizacao="PRICE",
        registro_entidade_ref=registro_ref,
    )


def _eventos_ledger(db_session: Session, operacao_id: uuid.UUID) -> list[str]:
    return [
        row.evento_tipo
        for row in db_session.execute(
            text(
                "select evento_tipo from capital_ledger "
                "where operacao_id = :id order by created_at, seq"
            ),
            {"id": str(operacao_id)},
        )
    ]


def _cadeia_integra(db_session: Session) -> bool:
    quebradas = db_session.execute(
        text("select count(*) from fn_verificar_cadeia_ledger()")
    ).scalar_one()
    return quebradas == 0


class TestNovacaoAtomica:
    def test_renegociacao_libera_antiga_e_ativa_nova_sem_dupla_contagem(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        # Capital 50k, antiga de 30k ativa. Renegociar para 35k só é
        # possível se a liberação da antiga for visível ao gate da nova
        # (35k > 20k disponíveis antes da liberação) — o sucesso da
        # ativação já prova que não há dupla contagem no teto.
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-OLD")

        antiga, nova = renegociar_operacao(db_session, op_id, _termos(35_000))

        assert antiga.status == "renegociada"
        assert nova.status == "ativa"
        assert nova.valor_principal == 35_000
        assert nova.registro_entidade_ref == "REG-NOVACAO"
        assert nova.tomador_id == antiga.tomador_id
        # Comprometido = só a nova: 50k - 35k = 15k
        assert consultar_capital_disponivel(db_session) == 15_000

    def test_renegociacao_acima_do_teto_nao_muda_nada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Atomicidade: OC001 na ativação da nova desfaz TUDO — inclusive
        a liberação da antiga e o evento de ledger já gravado no passo 1."""
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-OLD")
        eventos_antes = _eventos_ledger(db_session, op_id)

        with pytest.raises(TetoCapitalExcedido) as exc_info:
            renegociar_operacao(db_session, op_id, _termos(60_000))

        assert exc_info.value.sqlstate == "OC001"
        status = db_session.execute(
            text("select status from operacao_credito where id = :id"), {"id": str(op_id)}
        ).scalar_one()
        assert status == "ativa"  # antiga intacta
        total_ops = db_session.execute(text("select count(*) from operacao_credito")).scalar_one()
        assert total_ops == 1  # nenhuma nova operação vazou
        assert _eventos_ledger(db_session, op_id) == eventos_antes
        assert consultar_capital_disponivel(db_session) == 20_000

    def test_renegociacao_de_proposta_bloqueada_oc003(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000, status="proposta")

        with pytest.raises(TransicaoInvalida):
            renegociar_operacao(db_session, op_id, _termos(10_000))

    def test_renegociacao_de_inadimplente_funciona(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-OLD")
        marcar_inadimplente(db_session, op_id)

        antiga, nova = renegociar_operacao(db_session, op_id, _termos(32_000))

        assert antiga.status == "renegociada"
        assert nova.status == "ativa"
        assert consultar_capital_disponivel(db_session) == 18_000

    def test_renegociacao_operacao_inexistente(self, db_session: Session) -> None:
        with pytest.raises(OperacaoNaoEncontrada):
            renegociar_operacao(db_session, uuid.uuid4(), _termos(1_000))

    def test_ledger_da_novacao_e_cadeia_de_hash(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A novação grava DOIS eventos na mesma transação (liberação da
        antiga + ativação da nova) — o cenário que quebrava o desempate da
        cadeia de hash da 005 (created_at idêntico, ids aleatórios)."""
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-OLD")

        antiga, nova = renegociar_operacao(
            db_session, op_id, _termos(35_000), usuario_id="operador-renegociacao"
        )

        # Antiga: ativação original + liberação pela novação
        assert _eventos_ledger(db_session, op_id) == [
            "ativacao_operacao",
            "renegociacao_liberacao",
        ]
        assert _eventos_ledger(db_session, nova.id) == ["ativacao_operacao"]  # type: ignore[arg-type]
        # Autor propagado aos DOIS eventos da mesma transação da novação
        autor_liberacao = db_session.execute(
            text(
                "select usuario_id from capital_ledger "
                "where operacao_id = :id and evento_tipo = 'renegociacao_liberacao'"
            ),
            {"id": str(op_id)},
        ).scalar_one()
        autor_ativacao_nova = db_session.execute(
            text("select usuario_id from capital_ledger where operacao_id = :id"),
            {"id": str(nova.id)},
        ).scalar_one()
        assert autor_liberacao == autor_ativacao_nova == "operador-renegociacao"
        assert _cadeia_integra(db_session)


class TestInadimplenteComprometeCapital:
    """Furo G1 fechado: inadimplência NÃO abre teto."""

    def test_marcar_inadimplente_nao_libera_capital(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")

        marcar_inadimplente(db_session, op_id)

        assert consultar_capital_disponivel(db_session) == 20_000  # não 50_000

        op_b = _criar_operacao(db_session, tomador_autorizado, 25_000, registro_ref="REG-B")
        with pytest.raises(TetoCapitalExcedido):
            ativar_operacao(db_session, op_b)

    def test_inadimplencia_nao_gera_evento_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Movimento interno ao conjunto comprometido: sem evento de capital."""
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")

        marcar_inadimplente(db_session, op_id)
        regularizar_operacao(db_session, op_id)

        # Só a ativação original — sem 'ativacao_operacao' duplicado da cura
        assert _eventos_ledger(db_session, op_id) == ["ativacao_operacao"]
        assert consultar_capital_disponivel(db_session) == 20_000

    def test_liquidar_inadimplente_libera_capital_com_evento(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Antes da 006, inadimplente -> liquidada não gravava evento algum."""
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")
        marcar_inadimplente(db_session, op_id)

        op = liquidar_operacao(db_session, op_id)

        assert op.status == "liquidada"
        assert consultar_capital_disponivel(db_session) == 50_000
        assert _eventos_ledger(db_session, op_id) == ["ativacao_operacao", "liquidacao"]
        assert _cadeia_integra(db_session)

    def test_reducao_de_capital_conta_inadimplente_como_comprometido(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")
        marcar_inadimplente(db_session, op_id)

        with pytest.raises(Exception) as exc_info:
            db_session.execute(
                text(
                    "insert into esc_capital_social (valor, tipo_evento) values (25000, 'reducao')"
                )
            )
            db_session.commit()

        db_session.rollback()
        assert sqlstate_de(exc_info.value) == "OC005"

    def test_marcar_inadimplente_de_registrada_bloqueada_oc003(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000)

        with pytest.raises(TransicaoInvalida):
            marcar_inadimplente(db_session, op_id)


class TestLiquidacaoViaEngine:
    def test_liquidar_operacao_ativa(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")

        op = liquidar_operacao(db_session, op_id, usuario_id="operador-liquidacao")

        assert op.status == "liquidada"
        assert consultar_capital_disponivel(db_session) == 50_000
        autor = db_session.execute(
            text(
                "select usuario_id from capital_ledger "
                "where operacao_id = :id and evento_tipo = 'liquidacao'"
            ),
            {"id": str(op_id)},
        ).scalar_one()
        assert autor == "operador-liquidacao"

    def test_liquidar_proposta_bloqueada_oc003(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000, status="proposta")

        with pytest.raises(TransicaoInvalida):
            liquidar_operacao(db_session, op_id)
