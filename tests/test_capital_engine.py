"""
Suite pytest do motor de capital — porta os 7 cenários de
test_capital_invariant.sh + idempotência para a camada Python,
provando a tradução SQLSTATE -> exceção -> HTTP (RegraNegocioViolada).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import (
    ativar_operacao,
    consultar_capital_disponivel,
    consultar_capital_snapshot,
    criar_operacao,
    registrar_evento_capital,
    transicionar_operacao,
)
from app.core.exceptions import (
    MunicipioNaoAutorizado,
    OperacaoNaoEncontrada,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    TetoCapitalExcedido,
    TransicaoInvalida,
)
from tests.conftest import sqlstate_de


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
        assert sqlstate_de(exc_info.value) == "OC005"


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


class TestConsultarCapitalSnapshot:
    def test_snapshot_sem_operacoes(self, db_session: Session, capital_constituido: None) -> None:
        snapshot = consultar_capital_snapshot(db_session)
        assert snapshot.total == 50_000
        assert snapshot.comprometido == 0
        assert snapshot.disponivel == 50_000

    def test_snapshot_com_operacao_ativa(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        snapshot = consultar_capital_snapshot(db_session)
        assert snapshot.total == 50_000
        assert snapshot.comprometido == 30_000
        assert snapshot.disponivel == 20_000


# ---------------------------------------------------------------------------
# criar_operacao / transicionar_operacao / registrar_evento_capital
#
# Adicionadas nas fases F7/F8 e até aqui sem nenhum teste direto — eram os
# 35 statements que mantinham capital_engine.py em 58,8% de cobertura,
# justamente no arquivo que carrega o peso legal do Art. 5º.
# ---------------------------------------------------------------------------


class TestCriarOperacao:
    def test_cria_operacao_em_proposta(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Nasce em 'proposta' e NAO compromete capital — teto e gate
        geografico so sao avaliados na ativacao."""
        op = criar_operacao(
            db_session,
            tomador_id=tomador_autorizado,
            tipo="emprestimo",
            valor_principal=Decimal("10000.00"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=12,
        )
        assert op.status == "proposta"
        assert op.id is not None
        # Proposta nao entra no comprometido.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")

    def test_operacao_criada_nao_gera_evento_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Criar nao movimenta capital — o ledger so registra ativacao e
        liquidacao. Um evento aqui significaria capital comprometido cedo
        demais."""
        antes = db_session.execute(text("select count(*) from capital_ledger")).scalar_one()
        criar_operacao(
            db_session,
            tomador_id=tomador_autorizado,
            tipo="financiamento",
            valor_principal=Decimal("7500.00"),
            taxa_juros_mensal=Decimal("1.9"),
            sistema_amortizacao="SAC",
            numero_parcelas=24,
        )
        depois = db_session.execute(text("select count(*) from capital_ledger")).scalar_one()
        assert depois == antes


class TestTransicionarOperacao:
    def test_registrar_grava_referencia_e_habilita_ativacao(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """proposta -> registrada gravando registro_entidade_ref (Art. 5o §3o):
        sem ele a ativacao seria bloqueada por OC004."""
        op = criar_operacao(
            db_session,
            tomador_id=tomador_autorizado,
            tipo="emprestimo",
            valor_principal=Decimal("5000.00"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="PRICE",
            numero_parcelas=6,
        )
        registrada = transicionar_operacao(
            db_session, op.id, "registrada", registro_entidade_ref="B3-REG-2026-0001"
        )
        assert registrada.status == "registrada"
        assert registrada.registro_entidade_ref == "B3-REG-2026-0001"

        # Prova que a referencia realmente destrava a ativacao.
        ativa = ativar_operacao(db_session, op.id)
        assert ativa.status == "ativa"

    def test_liquidar_devolve_capital_e_grava_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """ativa -> liquidada libera o capital comprometido e deixa rastro."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("20000.00")

        liquidada = transicionar_operacao(db_session, op_id, "liquidada")
        assert liquidada.status == "liquidada"
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")

        eventos = (
            db_session.execute(
                text(
                    "select evento_tipo from capital_ledger "
                    "where operacao_id = :i order by created_at"
                ),
                {"i": str(op_id)},
            )
            .scalars()
            .all()
        )
        assert eventos == ["ativacao_operacao", "liquidacao"]

    def test_transicao_invalida_e_bloqueada_pelo_banco(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A maquina de estados vive no trigger (OC003), nao no Python —
        'registrada' nao pode saltar direto para 'liquidada'."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 3000)
        with pytest.raises(TransicaoInvalida) as exc:
            transicionar_operacao(db_session, op_id, "liquidada")
        assert sqlstate_de(exc.value) == "OC003"

    def test_operacao_inexistente(self, db_session: Session) -> None:
        with pytest.raises(OperacaoNaoEncontrada):
            transicionar_operacao(db_session, uuid.uuid4(), "cancelada")

    def test_cancelar_proposta_nao_toca_o_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Cancelar antes de ativar nao movimenta capital algum."""
        op = criar_operacao(
            db_session,
            tomador_id=tomador_autorizado,
            tipo="emprestimo",
            valor_principal=Decimal("1000.00"),
            taxa_juros_mensal=Decimal("3.0"),
            sistema_amortizacao="PRICE",
            numero_parcelas=3,
        )
        antes = db_session.execute(text("select count(*) from capital_ledger")).scalar_one()
        cancelada = transicionar_operacao(db_session, op.id, "cancelada")
        assert cancelada.status == "cancelada"
        depois = db_session.execute(text("select count(*) from capital_ledger")).scalar_one()
        assert depois == antes

    def test_registro_ref_ignorado_fora_da_transicao_registrada(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """registro_entidade_ref so se aplica ao virar 'registrada' — passa-lo
        em outra transicao nao deve sobrescrever nada."""
        op = criar_operacao(
            db_session,
            tomador_id=tomador_autorizado,
            tipo="emprestimo",
            valor_principal=Decimal("2000.00"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="PRICE",
            numero_parcelas=4,
        )
        cancelada = transicionar_operacao(
            db_session, op.id, "cancelada", registro_entidade_ref="NAO-DEVE-GRAVAR"
        )
        assert cancelada.registro_entidade_ref is None


class TestRegistrarEventoCapital:
    def test_aporte_eleva_o_teto(self, db_session: Session, capital_constituido: None) -> None:
        assert consultar_capital_snapshot(db_session).total == Decimal("50000.00")
        registrar_evento_capital(db_session, valor=Decimal("25000"), tipo_evento="constituicao")
        assert consultar_capital_snapshot(db_session).total == Decimal("75000.00")

    def test_reducao_abaixo_do_comprometido_e_bloqueada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """OC005: com 40.000 comprometidos de 50.000, reduzir 20.000 deixaria
        o capital abaixo do ja emprestado — o trigger recusa."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 40000)
        ativar_operacao(db_session, op_id)

        with pytest.raises(ReducaoCapitalBloqueada) as exc:
            registrar_evento_capital(db_session, valor=Decimal("20000"), tipo_evento="reducao")
        assert sqlstate_de(exc.value) == "OC005"

    def test_reducao_dentro_da_folga_e_permitida(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 10000)
        ativar_operacao(db_session, op_id)
        registrar_evento_capital(db_session, valor=Decimal("5000"), tipo_evento="reducao")
        assert consultar_capital_snapshot(db_session).total == Decimal("45000.00")
