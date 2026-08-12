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
    novar_operacao,
    registrar_evento_capital,
    transicionar_operacao,
)
from app.core.exceptions import (
    MunicipioNaoAutorizado,
    NovacaoForaDaTransacaoAtomica,
    OperacaoNaoEncontrada,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    TetoCapitalExcedido,
    TransicaoInvalida,
)
from tests.conftest import arquivar_identificacao, confirmar_registro, sqlstate_de


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
    op_id = result.scalar_one()

    # Desde a migration 013, ativar exige registro CONFIRMADO. `registro_ref
    # is None` passou a significar "operação sem registro" — que é
    # exatamente o cenário do teste de OC004.
    if registro_ref is not None:
        confirmar_registro(db_session, op_id)
    return op_id


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
        # Sem identificação o bloqueio viria de OC019 (migration 014) e o
        # teste deixaria de provar o que promete.
        arquivar_identificacao(db_session, tomador_fora_id)

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
        """proposta -> registrada gravando registro_entidade_ref.

        Desde a migration 013 essa referência é INFORMATIVA: quem destrava a
        ativação é o registro confirmado em entidade registradora. O teste
        guarda essa mudança — antes bastava o texto."""
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

        # A referência sozinha NÃO destrava mais.
        with pytest.raises(RegistroEntidadeAusente) as exc_info:
            ativar_operacao(db_session, op.id)
        assert exc_info.value.sqlstate == "OC004"

        # Com registro confirmado, ativa.
        confirmar_registro(db_session, op.id)
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


# ---------------------------------------------------------------------------
# Migration 006 — os dois furos de teto que ela fecha
#
# Ambos comprovados contra Postgres real ANTES da correção existir:
#   ativa -> inadimplente  liberou R$ 40.000,00 | eventos no ledger: 0
#   ativa -> renegociada   liberou R$ 40.000,00 | eventos no ledger: 0
# ---------------------------------------------------------------------------


class TestInadimplenteComprometeCapital:
    def test_marcar_inadimplente_nao_libera_capital(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O dinheiro nao voltou: o titulo sai de 'ativa', mas continua
        ocupando o teto do Art. 5o. Antes da 006 isso liberava o valor
        inteiro e permitia emprestar de novo o mesmo capital."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 40000)
        ativar_operacao(db_session, op_id)
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("40000.00")

        transicionar_operacao(db_session, op_id, "inadimplente")

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("40000.00")
        assert consultar_capital_disponivel(db_session) == Decimal("10000.00")

    def test_inadimplente_nao_gera_evento_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Nao ha movimento de capital, entao nao ha o que registrar no
        ledger de CAPITAL. Quem marcou fica na trilha da aplicacao."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 10000)
        ativar_operacao(db_session, op_id)
        antes = db_session.execute(text("select count(*) from capital_ledger")).scalar_one()

        transicionar_operacao(db_session, op_id, "inadimplente")

        depois = db_session.execute(text("select count(*) from capital_ledger")).scalar_one()
        assert depois == antes

    def test_teto_bloqueia_nova_operacao_com_capital_preso_em_inadimplente(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O teste que prova o furo fechado: com 40.000 inadimplentes de
        50.000, uma nova operacao de 20.000 NAO cabe. Antes da 006 cabia."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 40000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "inadimplente")

        outra = _criar_operacao(db_session, tomador_autorizado, 20000)
        with pytest.raises(TetoCapitalExcedido) as exc:
            ativar_operacao(db_session, outra)
        assert sqlstate_de(exc.value) == "OC001"

    def test_liquidar_inadimplente_devolve_capital_com_evento(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """inadimplente -> liquidada e uma SAIDA real do comprometido, e
        agora gera evento (antes da 006 esse caminho nao gerava nada)."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "inadimplente")

        transicionar_operacao(db_session, op_id, "liquidada")

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")
        eventos = (
            db_session.execute(
                text(
                    "select evento_tipo from capital_ledger where operacao_id = :i"
                    " order by created_at"
                ),
                {"i": str(op_id)},
            )
            .scalars()
            .all()
        )
        assert eventos == ["ativacao_operacao", "liquidacao"]

    def test_regularizar_inadimplente_nao_duplica_evento(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """inadimplente -> ativa nao muda o comprometido (os dois ocupam o
        teto), entao nao pode gravar uma segunda ativacao — isso contaria o
        mesmo dinheiro duas vezes no ledger."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 15000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "inadimplente")

        ativar_operacao(db_session, op_id)

        eventos = (
            db_session.execute(
                text("select evento_tipo from capital_ledger where operacao_id = :i"),
                {"i": str(op_id)},
            )
            .scalars()
            .all()
        )
        assert eventos == ["ativacao_operacao"]
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("15000.00")


class TestNovacaoAtomica:
    def test_renegociar_direto_e_bloqueado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Sem a novacao atomica, a original sairia do comprometido e nada
        impediria criar a substituta depois — capital contado duas vezes em
        janelas diferentes."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)

        with pytest.raises(NovacaoForaDaTransacaoAtomica) as exc:
            transicionar_operacao(db_session, op_id, "renegociada")
        assert sqlstate_de(exc.value) == "OC008"

    def test_novacao_baixa_original_e_cria_substituta(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 40000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("25000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )

        original = db_session.execute(
            text("select status from operacao_credito where id = :i"), {"i": str(op_id)}
        ).scalar_one()
        assert original == "renegociada"
        assert nova.status == "registrada"
        assert str(nova.substitui_operacao_id) == str(op_id)

        # A substituta ainda NAO compromete: nasce em 'registrada'.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")

    def test_novacao_registra_evento_de_saida_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A renegociacao move capital (libera a original), entao TEM que
        aparecer no ledger — antes da 006 nao aparecia, e a serie temporal
        do dashboard mentia."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("10000"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="SAC",
            numero_parcelas=12,
        )

        eventos = (
            db_session.execute(
                text(
                    "select evento_tipo from capital_ledger where operacao_id = :i"
                    " order by created_at"
                ),
                {"i": str(op_id)},
            )
            .scalars()
            .all()
        )
        assert eventos == ["ativacao_operacao", "renegociacao"]

    def test_sem_dupla_contagem_ao_ativar_a_substituta(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O teste central da novacao: 40.000 originais + 25.000 substitutos
        NAO podem somar 65.000 de comprometido."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 40000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("25000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )
        # A substituta é um título novo: precisa do próprio registro.
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("25000.00")

    def test_novacao_de_operacao_nao_renegociavel_e_recusada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """So 'ativa' ou 'inadimplente' podem ser renegociadas."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 5000)  # fica em 'registrada'

        with pytest.raises(TransicaoInvalida):
            novar_operacao(
                db_session,
                op_id,
                valor_principal=Decimal("1000"),
                taxa_juros_mensal=Decimal("1.0"),
                sistema_amortizacao="PRICE",
                numero_parcelas=6,
            )

    def test_novacao_de_inadimplente_e_permitida(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Renegociar um inadimplente e o caso de uso mais comum de novacao."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "inadimplente")

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("22000"),
            taxa_juros_mensal=Decimal("3.0"),
            sistema_amortizacao="PRICE",
            numero_parcelas=36,
        )

        assert nova.status == "registrada"
        # A original saiu do comprometido; a substituta ainda nao entrou.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")


# ---------------------------------------------------------------------------
# Migration 015 — as bordas do teto
#
# Os tres furos que a 015 fecha tinham em comum o fato de nao passarem por
# transicao nenhuma: a 003/006/013/014 vigiam a ENTRADA e a SAIDA do estado
# comprometido, e nada vigiava o que acontece com a linha DEPOIS. Todos eram
# alcancaveis por SQL direto, todos moviam o teto do Art. 5o e nenhum deles
# deixava evento no capital_ledger.
# ---------------------------------------------------------------------------


def _bloqueio(db_session: Session, sql: str, params: dict | None = None) -> BaseException:
    """Executa SQL cru esperando recusa do banco e devolve a excecao.

    A sessao de teste usa savepoints (ver conftest.db_session): o rollback()
    aqui volta ao ponto do ultimo commit, entao tudo o que o setup ja commitou
    continua de pe e o teste pode seguir asserindo sobre o estado.
    """
    with pytest.raises(Exception) as exc_info:
        db_session.execute(text(sql), params or {})
        db_session.commit()
    db_session.rollback()
    return exc_info.value


def _constraint_violada(exc: BaseException) -> str | None:
    """Nome da CHECK constraint violada.

    Pela mesma disciplina do `sqlstate_de`: identificar por metadado do
    driver (psycopg expoe em `.diag.constraint_name`), nunca por substring da
    mensagem. Com 23514 sozinho o teste provaria "alguma constraint recusou";
    com o nome, prova qual.
    """
    orig = getattr(exc, "orig", exc)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


class TestOperacaoComprometidaEhImutavel:
    """OC020: o que ja compromete capital nao se reescreve por UPDATE.

    O furo (a): o trigger do teto avalia os gates na ENTRADA no estado
    comprometido e na SAIDA. Um UPDATE ativa -> ativa nao e nem uma coisa nem
    outra, e a checagem da maquina de estados tambem e pulada, porque esta
    sob `if tg_op = UPDATE and new.status is distinct from old.status`.
    """

    def test_bloqueia_inflar_valor_principal_de_operacao_ativa(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O cenario exato do furo: 50.000 de capital, 30.000 ativos, e um
        UPDATE que deixaria 500.000 comprometidos — dez vezes o teto."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        exc = _bloqueio(
            db_session,
            "update operacao_credito set valor_principal = 500000 where id = :i",
            {"i": str(op_id)},
        )

        assert sqlstate_de(exc) == "OC020"
        # E o teto continua onde estava: nem o comprometido subiu, nem
        # apareceu evento novo no ledger para justificar a subida.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")
        eventos = db_session.execute(
            text("select evento_tipo, valor from capital_ledger where operacao_id = :i"),
            {"i": str(op_id)},
        ).all()
        assert [(e.evento_tipo, e.valor) for e in eventos] == [
            ("ativacao_operacao", Decimal("30000.00"))
        ]

    def test_bloqueia_troca_de_tomador_em_operacao_ativa(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Trocar o tomador depois de ativa contornaria os dois gates que so
        rodam na ativacao: municipio autorizado (OC002) e identificacao
        arquivada (OC019). O emprestimo passaria a ser de outra pessoa sem
        que nenhum deles fosse consultado."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000)
        ativar_operacao(db_session, op_id)

        outro = db_session.execute(
            text(
                """
                insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
                values (:cnpj, 'Oficina Fora ME', 'ME', 'Goiânia', 'GO', false)
                returning id
                """
            ),
            {"cnpj": f"{uuid.uuid4().int % 10**14:014d}"},
        ).scalar_one()
        db_session.commit()

        exc = _bloqueio(
            db_session,
            "update operacao_credito set tomador_id = :t where id = :i",
            {"t": str(outro), "i": str(op_id)},
        )

        assert sqlstate_de(exc) == "OC020"

    def test_bloqueia_reescrita_da_agenda_em_operacao_inadimplente(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """'inadimplente' compromete capital desde a 006, entao congela junto.

        Congelar so 'ativa' deixaria a porta aberta pelo caminho
        ativa -> inadimplente -> edita -> ativa. Taxa e numero de parcelas
        definem a agenda que a 007 gerou na ativacao e que a 009 baixa contra
        movimento bancario — reescreve-las e refazer o contrato sem novacao.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 20_000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "inadimplente")

        exc_taxa = _bloqueio(
            db_session,
            "update operacao_credito set taxa_juros_mensal = 0.1 where id = :i",
            {"i": str(op_id)},
        )
        assert sqlstate_de(exc_taxa) == "OC020"

        exc_parcelas = _bloqueio(
            db_session,
            "update operacao_credito set numero_parcelas = 360 where id = :i",
            {"i": str(op_id)},
        )
        assert sqlstate_de(exc_parcelas) == "OC020"

    def test_bloqueia_liquidar_trocando_o_valor_no_mesmo_update(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O caso mais perigoso, coberto porque a checagem olha OLD.status.

        Sem isso, o bloco de SAIDA do trigger do teto gravaria no ledger o
        `new.valor_principal` — liberando mais capital do que foi
        comprometido, com a cadeia de hash intacta, porque nada foi adulterado
        depois do fato: a mentira entra ja assinada.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000)
        ativar_operacao(db_session, op_id)

        exc = _bloqueio(
            db_session,
            "update operacao_credito set status = 'liquidada', valor_principal = 49000 "
            "where id = :i",
            {"i": str(op_id)},
        )

        assert sqlstate_de(exc) == "OC020"
        # A operacao continua ativa e o ledger nao ganhou liquidacao alguma.
        status = db_session.execute(
            text("select status from operacao_credito where id = :i"), {"i": str(op_id)}
        ).scalar_one()
        assert status == "ativa"
        eventos = (
            db_session.execute(
                text("select evento_tipo from capital_ledger where operacao_id = :i"),
                {"i": str(op_id)},
            )
            .scalars()
            .all()
        )
        assert eventos == ["ativacao_operacao"]

    def test_bloqueia_delete_de_operacao_comprometida(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A 015 nao criou trigger de DELETE em operacao_credito, e o motivo
        precisa de prova, nao de argumento.

        O argumento: as FKs que apontam para operacao_credito (capital_ledger,
        parcela, operacao_evento, contrato, registro) nao declaram `on delete`,
        e toda operacao que chegou a comprometer capital tem pelo menos o
        evento 'ativacao_operacao' apontando para ela — entao o proprio banco
        recusa com 23503, sem precisar de PL/pgSQL. Correto hoje; frágil
        amanha, e a fragilidade e silenciosa: um `on delete cascade` numa
        migration futura faria o DELETE devolver 30.000 ao teto E levar junto
        o evento de ledger que provava a saida.

        Por isso o teste tem duas metades. A comportamental (o 23503) prova
        que o caminho esta fechado HOJE, mas sozinha nao discrimina: com meia
        duzia de FKs sem `on delete`, basta uma continuar restritiva para o
        23503 aparecer e o teste passar por cima de um cascade recem-aberto na
        FK que importa. A estrutural le o catalogo e exige que NENHUMA delas
        tenha acao de delete — e essa falha no ato.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        exc = _bloqueio(db_session, "delete from operacao_credito where id = :i", {"i": str(op_id)})

        assert sqlstate_de(exc) == "23503"
        # A operacao continua de pe, ocupando o teto, e o evento que provou a
        # ativacao continua no ledger.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")
        assert (
            db_session.execute(
                text("select count(*) from capital_ledger where operacao_id = :i"),
                {"i": str(op_id)},
            ).scalar_one()
            == 1
        )

        # confdeltype: 'a' = no action, 'r' = restrict (os dois recusam);
        # 'c' = cascade, 'n' = set null, 'd' = set default (os tres apagariam
        # ou desamarrariam a prova junto com a operacao).
        permissivas = db_session.execute(
            text(
                """
                select conrelid::regclass::text as tabela, conname, confdeltype
                from pg_constraint
                where contype = 'f'
                  and confrelid = 'operacao_credito'::regclass
                  and confdeltype not in ('a','r')
                order by 1, 2
                """
            )
        ).all()
        assert not permissivas, (
            "FK apontando para operacao_credito com acao de delete: "
            f"{[(p.tabela, p.conname, p.confdeltype) for p in permissivas]}. "
            "Apagar uma operacao comprometida deixaria de ser recusado pelo banco, e a "
            "015 nao tem trigger de DELETE porque conta com essa recusa."
        )

    def test_campo_nao_congelado_continua_editavel_em_operacao_ativa(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Caminho feliz: o congelamento e dos quatro campos economicos, nao
        da linha inteira.

        registro_entidade_ref e referencia informativa desde a 013 (quem
        destrava a ativacao e o registro confirmado em registro_operacao) e e
        corrigido em operacao viva. Travar isso seria travar operacao
        legitima."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000)
        ativar_operacao(db_session, op_id)

        db_session.execute(
            text(
                "update operacao_credito set registro_entidade_ref = 'B3-CORRIGIDO' where id = :i"
            ),
            {"i": str(op_id)},
        )
        db_session.commit()

        ref = db_session.execute(
            text("select registro_entidade_ref from operacao_credito where id = :i"),
            {"i": str(op_id)},
        ).scalar_one()
        assert ref == "B3-CORRIGIDO"
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("10000.00")

    def test_valor_ainda_e_editavel_antes_de_comprometer(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Caminho feliz: enquanto a operacao nao ocupa o teto, ela e uma
        proposta em negociacao — corrigir o valor e o trabalho normal do
        operador, e a ativacao depois avalia o valor NOVO contra o teto."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000)

        db_session.execute(
            text("update operacao_credito set valor_principal = 45000 where id = :i"),
            {"i": str(op_id)},
        )
        db_session.commit()

        ativar_operacao(db_session, op_id)
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("45000.00")

    def test_liquidacao_normal_continua_funcionando(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Caminho feliz: mudar SO o status de uma operacao comprometida
        continua livre — o congelamento e dos campos economicos, e a maquina
        de estados segue sendo a da 006."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        transicionar_operacao(db_session, op_id, "liquidada")

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")

    def test_novacao_continua_sendo_o_caminho_para_mudar_valor(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Caminho feliz que fecha o argumento: o congelamento nao impede
        renegociar, so obriga a fazer pela porta que baixa a original e cria a
        substituta sob o mesmo lock, na mesma transacao."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("12000"),
            taxa_juros_mensal=Decimal("1.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=18,
        )

        assert nova.valor_principal == Decimal("12000.00")
        assert str(nova.substitui_operacao_id) == str(op_id)


class TestCapitalSocialEhAppendOnly:
    """OC021: o furo (b) — a tabela que define o teto era mutavel.

    A 003 criou o trigger `before insert on esc_capital_social` e a 006
    redefiniu a FUNCAO sem nunca recriar o trigger. Nao havia UPDATE nem
    DELETE vigiado, e v_capital_atual soma a tabela em tempo real.
    """

    def test_bloqueia_delete_de_constituicao(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Apagar a constituicao derrubava o teto para zero na hora, com
        30.000 comprometidos, sem disparar OC005 (que so olha INSERT)."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        exc = _bloqueio(
            db_session, "delete from esc_capital_social where tipo_evento = 'constituicao'"
        )

        assert sqlstate_de(exc) == "OC021"
        assert consultar_capital_snapshot(db_session).total == Decimal("50000.00")

    def test_bloqueia_update_de_evento_de_capital(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        """Editar o valor da constituicao move o teto nos dois sentidos: para
        baixo, desenquadra operacoes ja ativas; para cima, autoriza emprestar
        capital que nunca foi integralizado."""
        exc = _bloqueio(
            db_session,
            "update esc_capital_social set valor = 900000 where tipo_evento = 'constituicao'",
        )

        assert sqlstate_de(exc) == "OC021"
        assert consultar_capital_snapshot(db_session).total == Decimal("50000.00")

    def test_bloqueia_delete_de_reducao(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O ataque inverso, que nenhuma checagem de 'capital resultante vs.
        comprometido' pegaria: apagar uma reducao AUMENTA o teto. Por isso o
        bloqueio da 015 e seco, e nao condicional."""
        registrar_evento_capital(db_session, valor=Decimal("20000"), tipo_evento="reducao")
        assert consultar_capital_snapshot(db_session).total == Decimal("30000.00")

        exc = _bloqueio(db_session, "delete from esc_capital_social where tipo_evento = 'reducao'")

        assert sqlstate_de(exc) == "OC021"
        assert consultar_capital_snapshot(db_session).total == Decimal("30000.00")

    def test_reducao_legitima_continua_passando_pelo_oc005(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Caminho feliz + prova de que OC005 nao foi tocado: reduzir capital
        continua sendo INSERIR um evento 'reducao', a que cabe na folga passa
        e a que nao cabe e recusada com o mesmo codigo de sempre."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        registrar_evento_capital(db_session, valor=Decimal("15000"), tipo_evento="reducao")
        assert consultar_capital_snapshot(db_session).total == Decimal("35000.00")

        with pytest.raises(ReducaoCapitalBloqueada) as exc:
            registrar_evento_capital(db_session, valor=Decimal("10000"), tipo_evento="reducao")
        assert sqlstate_de(exc.value) == "OC005"

    def test_aporte_continua_elevando_o_teto(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        """Caminho feliz: append-only bloqueia UPDATE e DELETE, nunca INSERT."""
        registrar_evento_capital(db_session, valor=Decimal("30000"), tipo_evento="constituicao")
        assert consultar_capital_snapshot(db_session).total == Decimal("80000.00")


class TestDominioDeValoresNoBanco:
    """O furo (c): valor positivo e dominio de evento eram invariantes so do
    Pydantic — protegiam o endpoint, e so o endpoint."""

    def test_recusa_reducao_com_valor_negativo(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        """O ataque mais elegante dos tres: uma 'reducao' de -100.000 INFLA o
        teto. A view faz `when reducao then -valor`, e fn_check_reducao_capital
        calcula `capital_atual - new.valor`, que com valor negativo cresce — a
        reducao passa pelo OC005 justamente por ser um aporte disfarcado."""
        exc = _bloqueio(
            db_session,
            "insert into esc_capital_social (valor, tipo_evento) values (-100000, 'reducao')",
        )

        assert sqlstate_de(exc) == "23514"
        assert _constraint_violada(exc) == "esc_capital_social_valor_positivo"
        assert consultar_capital_snapshot(db_session).total == Decimal("50000.00")

    def test_recusa_tipo_evento_fora_do_dominio(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        """Sem o dominio fechado, um tipo_evento desconhecido caia no `else 0`
        da view v_capital_atual: entrava na tabela e sumia do teto, sem erro."""
        exc = _bloqueio(
            db_session,
            "insert into esc_capital_social (valor, tipo_evento) values (100000, 'aporte_futuro')",
        )

        assert sqlstate_de(exc) == "23514"
        assert _constraint_violada(exc) == "esc_capital_social_tipo_evento_valido"
        assert consultar_capital_snapshot(db_session).total == Decimal("50000.00")

    def test_recusa_operacao_com_valor_principal_negativo(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Valor negativo em operacao ativa SUBTRAI do comprometido: seria
        capital disponivel criado do nada, dentro da propria soma do teto."""
        exc = _bloqueio(
            db_session,
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status)
            values (:t, 'emprestimo', -5000, 2.5, 'PRICE', 12, 'registrada')
            """,
            {"t": str(tomador_autorizado)},
        )

        assert sqlstate_de(exc) == "23514"
        assert _constraint_violada(exc) == "operacao_credito_valor_principal_positivo"

    def test_recusa_operacao_com_zero_parcelas(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Agenda de zero parcelas e emprestimo sem plano de pagamento: a
        geracao da 007 nao produz linha nenhuma e a operacao compromete
        capital sem nunca ter o que baixar."""
        exc = _bloqueio(
            db_session,
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status)
            values (:t, 'emprestimo', 5000, 2.5, 'PRICE', 0, 'registrada')
            """,
            {"t": str(tomador_autorizado)},
        )

        assert sqlstate_de(exc) == "23514"
        assert _constraint_violada(exc) == "operacao_credito_numero_parcelas_positivo"

    def test_valores_positivos_continuam_entrando(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Caminho feliz dos CHECKs: o fluxo normal — aporte, operacao,
        ativacao — nao encosta em nenhuma das quatro constraints."""
        registrar_evento_capital(db_session, valor=Decimal("10000"), tipo_evento="constituicao")

        op_id = _criar_operacao(db_session, tomador_autorizado, 55_000)
        ativar_operacao(db_session, op_id)

        assert consultar_capital_snapshot(db_session).total == Decimal("60000.00")
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("55000.00")
