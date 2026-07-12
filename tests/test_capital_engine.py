"""
Suite pytest do motor de capital — porta os 7 cenários de
test_capital_invariant.sh + idempotência para a camada Python,
provando a tradução pgcode -> exceção -> HTTP (RegraNegocioViolada).
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, consultar_capital_disponivel
from app.core.exceptions import (
    MunicipioNaoAutorizado,
    OperacaoNaoEncontrada,
    RegistroEntidadeAusente,
    TetoCapitalExcedido,
    TransicaoInvalida,
)


def _criar_operacao(
    db_session: Session,
    tomador_id: uuid.UUID,
    valor: int,
    status: str = "registrada",
    registro_ref: str | None = "REG-TEST",
) -> uuid.UUID:
    result = db_session.execute(
        text(
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values
                (:tomador_id, 'emprestimo', :valor, 2.5, 'PRICE', 12, :status, :registro_ref)
            returning id
            """
        ),
        {
            "tomador_id": str(tomador_id),
            "valor": valor,
            "status": status,
            "registro_ref": registro_ref,
        },
    )
    db_session.commit()
    return result.scalar_one()


def _criar_e_ativar_operacao_direto(
    db_session: Session, tomador_id: uuid.UUID, valor: int, registro_ref: str = "REG-TEST"
) -> uuid.UUID:
    """
    Cria uma operação já ativa, fora da API — para preparar cenários de
    teste que dependem de capital já comprometido. A máquina de estados do
    trigger só permite INSERT em 'proposta'/'registrada'; por isso insere
    como 'registrada' e ativa via UPDATE em seguida.
    """
    op_id = _criar_operacao(db_session, tomador_id, valor, registro_ref=registro_ref)
    db_session.execute(
        text("update operacao_credito set status = 'ativa' where id = :id"), {"id": str(op_id)}
    )
    db_session.commit()
    return op_id


class TestAtivacaoDentroDoTeto:
    """Cenário 1: operação dentro do capital disponível ativa normalmente."""

    def test_ativa_operacao_dentro_do_teto(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)

        op = ativar_operacao(db_session, op_id)

        assert op.status == "ativa"


class TestTetoCapitalExcedido:
    """Cenário 2: operação que excede o disponível é bloqueada com OC001."""

    def test_bloqueia_operacao_acima_do_disponivel(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")
        op_id_excedente = _criar_operacao(
            db_session, tomador_autorizado, 25_000, registro_ref="REG-B"
        )

        with pytest.raises(TetoCapitalExcedido) as exc_info:
            ativar_operacao(db_session, op_id_excedente)

        assert exc_info.value.sqlstate == "OC001"
        assert exc_info.value.http_status == 422


class TestGateGeografico:
    """Cenário 3: tomador fora do município autorizado é bloqueado com OC002."""

    def test_bloqueia_tomador_fora_do_municipio(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        result = db_session.execute(
            text(
                """
                insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
                values (:cnpj, 'Comércio Fora ME', 'ME', 'Goiânia', 'GO', false)
                returning id
                """
            ),
            {"cnpj": f"{uuid.uuid4().int % 10**14:014d}"},
        )
        db_session.commit()
        tomador_fora_id = result.scalar_one()

        op_id = _criar_operacao(db_session, tomador_fora_id, 5_000)

        with pytest.raises(MunicipioNaoAutorizado) as exc_info:
            ativar_operacao(db_session, op_id)

        assert exc_info.value.sqlstate == "OC002"


class TestLiquidacaoLiberaCapital:
    """Cenário 4: liquidar uma operação libera capital para uma nova ativação."""

    def test_liquidacao_libera_capital_para_nova_operacao(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_a_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_a_id)

        op_b_id = _criar_operacao(db_session, tomador_autorizado, 25_000)
        with pytest.raises(TetoCapitalExcedido):
            ativar_operacao(db_session, op_b_id)

        db_session.execute(
            text("update operacao_credito set status = 'liquidada' where id = :id"),
            {"id": str(op_a_id)},
        )
        db_session.commit()

        op_b = ativar_operacao(db_session, op_b_id)
        assert op_b.status == "ativa"


class TestReducaoCapitalVigiada:
    """Cenário 5: reduzir capital abaixo do comprometido é bloqueado com OC005."""

    def test_bloqueia_reducao_abaixo_do_comprometido(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        with pytest.raises(Exception) as exc_info:
            db_session.execute(
                text(
                    "insert into esc_capital_social (valor, tipo_evento) values (40000, 'reducao')"
                )
            )
            db_session.commit()

        db_session.rollback()
        pgcode = getattr(getattr(exc_info.value, "orig", None), "pgcode", None)
        assert pgcode == "OC005"


class TestMaquinaDeEstados:
    """Cenário 6: transição proposta -> ativa direto é bloqueada com OC003."""

    def test_bloqueia_transicao_proposta_para_ativa(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 1_000, status="proposta")

        with pytest.raises(TransicaoInvalida) as exc_info:
            ativar_operacao(db_session, op_id)

        assert exc_info.value.sqlstate == "OC003"
        assert exc_info.value.http_status == 409


class TestRegistroEntidadeObrigatorio:
    """Cenário 7: ativar sem registro_entidade_ref é bloqueado com OC004."""

    def test_bloqueia_ativacao_sem_registro(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 1_000, registro_ref=None)

        with pytest.raises(RegistroEntidadeAusente) as exc_info:
            ativar_operacao(db_session, op_id)

        assert exc_info.value.sqlstate == "OC004"


class TestOperacaoInexistente:
    def test_operacao_nao_encontrada(self, db_session: Session) -> None:
        with pytest.raises(OperacaoNaoEncontrada):
            ativar_operacao(db_session, uuid.uuid4())


class TestIdempotenciaAtivacao:
    """
    Prova que o retry de rede do POST /ativar não duplica capital nem
    o evento no ledger — propriedade identificada na análise de arquitetura
    (Fase 0) como correta mas não testada.
    """

    def test_ativar_operacao_ja_ativa_nao_duplica_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        eventos_antes = db_session.execute(
            text("select count(*) from capital_ledger where operacao_id = :id"),
            {"id": str(op_id)},
        ).scalar_one()

        # Simula retry: chama ativar_operacao de novo sobre uma operação já ativa
        op_retry = ativar_operacao(db_session, op_id)

        eventos_depois = db_session.execute(
            text("select count(*) from capital_ledger where operacao_id = :id"),
            {"id": str(op_id)},
        ).scalar_one()

        assert op_retry.status == "ativa"
        assert eventos_antes == eventos_depois == 1


class TestTrilhaDeAuditoriaComAutor:
    """
    Migration 004 (Fase 6): usuario_id propagado via SET LOCAL app.user_id
    é registrado no capital_ledger pelo trigger.
    """

    def test_ativacao_com_usuario_id_registra_autor_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)

        ativar_operacao(db_session, op_id, usuario_id="operador-teste-123")

        autor = db_session.execute(
            text("select usuario_id from capital_ledger where operacao_id = :id"),
            {"id": str(op_id)},
        ).scalar_one()

        assert autor == "operador-teste-123"

    def test_ativacao_sem_usuario_id_nao_quebra(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Compatibilidade retroativa: chamadas sem usuario_id continuam funcionando."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)

        op = ativar_operacao(db_session, op_id)

        assert op.status == "ativa"
        autor = db_session.execute(
            text("select usuario_id from capital_ledger where operacao_id = :id"),
            {"id": str(op_id)},
        ).scalar_one()
        assert autor is None


class TestConsultarCapitalDisponivel:
    def test_consulta_capital_disponivel_sem_operacoes(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        disponivel = consultar_capital_disponivel(db_session)
        assert disponivel == 50_000

    def test_consulta_capital_disponivel_com_operacao_ativa(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        disponivel = consultar_capital_disponivel(db_session)
        assert disponivel == 20_000
