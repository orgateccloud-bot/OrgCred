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
    LiquidacaoSemQuitacao,
    MunicipioNaoAutorizado,
    NovacaoForaDaTransacaoAtomica,
    NovacaoSemLastro,
    OperacaoNaoEncontrada,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    RegraNegocioViolada,
    TetoCapitalExcedido,
    TransicaoInvalida,
)
from tests.conftest import (
    arquivar_identificacao,
    baixar_parcelas,
    confirmar_registro,
    envelhecer_encerramento,
    quitar_operacao,
    sqlstate_de,
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

        # Desde a migration 017, liquidar exige a agenda inteira baixada
        # contra movimento bancário — inclusive por SQL cru, porque o gate
        # vive no trigger e não no endpoint.
        assert quitar_operacao(db_session, op_a_id) == 12
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

    def test_liquidar_com_parcelas_abertas_e_bloqueado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O FURO QUE A 017 FECHOU, agora provado pelo avesso.

        Este teste existia e afirmava o contrário: liquidava uma operacao de
        20.000 com as DOZE parcelas em aberto e assertava `comprometido == 0`
        — ou seja, a suite provava que 100% do capital voltava ao teto sem um
        centavo comprovado, tirava a operacao do aging e matava a cobranca. A
        transicao passava porque a maquina de estados a autorizava e o bloco
        de saida do trigger nao olhava parcela nenhuma.

        Agora a recusa e OC022 e nada se move: nem o comprometido, nem o
        ledger, nem o status.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("20000.00")

        with pytest.raises(LiquidacaoSemQuitacao) as exc:
            transicionar_operacao(db_session, op_id, "liquidada")
        assert exc.value.sqlstate == "OC022"
        assert exc.value.http_status == 422

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("20000.00")
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

    def test_liquidar_com_uma_unica_parcela_em_aberto_ainda_e_bloqueado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Onze de doze pagas nao e quitacao — e a borda que interessa.

        Um gate escrito como "a maioria das parcelas" ou "o valor recebido
        cobre o principal" passaria aqui, e a diferenca entre passar e nao
        passar e todo o ponto: o teto so pode receber de volta o que voltou
        INTEIRO. A mensagem cita a contagem justamente para o operador saber
        quantas faltam."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)
        baixar_parcelas(db_session, op_id, list(range(1, 12)))

        with pytest.raises(LiquidacaoSemQuitacao) as exc:
            transicionar_operacao(db_session, op_id, "liquidada")
        assert exc.value.sqlstate == "OC022"
        assert "1 de 12" in str(exc.value)

    def test_liquidar_operacao_sem_agenda_nenhuma_e_bloqueado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """AGENDA VAZIA E RECUSA, nao aprovacao por vacuidade.

        O ramo que este teste exercita e o unico do gate que um `not exists
        (parcela em aberto)` escrito de forma ingenua erraria: com zero
        parcelas, "nenhuma esta em aberto" e VERDADEIRO, e o furo voltaria
        inteiro — 100% do capital devolvido ao teto sem uma linha de agenda
        para comprovar coisa alguma.

        Pelo caminho normal o ramo e inalcancavel (a 007 gera a agenda no
        gatilho de ativacao), e e exatamente por isso que ele precisa de um
        teste: sem um, a clausula `v_parcelas_totais = 0` poderia ser apagada
        por engano e a suite inteira continuaria verde. O cenario e montado
        desligando `trg_parcela_imutavel` (mesmo recurso que
        tests/test_baixa_recebimento.py e tests/test_aging.py ja usam), que e
        a forma de simular o estado que existiria se aquele gatilho um dia
        mudasse.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)

        db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
        db_session.execute(text("delete from parcela where operacao_id = :i"), {"i": str(op_id)})
        db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
        db_session.commit()

        with pytest.raises(LiquidacaoSemQuitacao) as exc:
            transicionar_operacao(db_session, op_id, "liquidada")
        assert exc.value.sqlstate == "OC022"
        assert "agenda de parcelas" in str(exc.value)

        # E o capital continua comprometido: a recusa e do ATO, entao nada
        # chegou ao bloco de saida do trigger.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("20000.00")

    def test_quitacao_com_todas_as_parcelas_baixadas_devolve_capital(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """CAMINHO FELIZ: com a agenda inteira baixada contra movimento
        bancario, liquidar continua devolvendo o capital e gravando
        'liquidacao' — o gate recusa a liquidacao sem prova, nao a
        liquidacao."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)
        assert quitar_operacao(db_session, op_id) == 12

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

    def test_write_off_encerra_a_cobranca_sem_devolver_capital(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A OUTRA METADE DA POLITICA (DECISOES_PENDENTES.md §6).

        Write-off encerra a cobranca — a operacao sai de `v_aging_operacoes` —
        e NAO devolve capital: o dinheiro nao voltou. O evento no ledger e
        'baixa_prejuizo', distinto de 'liquidacao', para a auditoria separar
        "foi pago" de "foi perdoado" sem interpretar valores. E o
        `saldo_disponivel_pos` gravado e o disponivel REAL depois do ato, que
        e o mesmo de antes: o write-off nao move o teto.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)

        baixada = transicionar_operacao(db_session, op_id, "baixada_prejuizo")
        assert baixada.status == "baixada_prejuizo"

        # O capital continua comprometido — e essa e a decisao, nao um bug.
        snapshot = consultar_capital_snapshot(db_session)
        assert snapshot.comprometido == Decimal("20000.00")
        assert snapshot.disponivel == Decimal("30000.00")
        assert consultar_capital_disponivel(db_session) == Decimal("30000.00")

        # Mas a cobranca acabou: fora do aging, com as parcelas ainda abertas
        # (elas sao a prova documental de quanto ficou por receber).
        assert (
            db_session.execute(
                text("select count(*) from v_aging_operacoes where operacao_id = :i"),
                {"i": str(op_id)},
            ).scalar_one()
            == 0
        )
        assert (
            db_session.execute(
                text("select count(*) from parcela where operacao_id = :i and status = 'aberta'"),
                {"i": str(op_id)},
            ).scalar_one()
            == 12
        )

        # Ordenado por `sorted` e nao por created_at: o default da coluna e
        # `now()`, que na sessao de teste (savepoints dentro de UMA transacao
        # externa — ver conftest.db_session) e IDENTICO para todas as linhas.
        # Ordenar por ele aqui daria uma ordem arbitraria e um teste piscante.
        eventos = (
            db_session.execute(
                text("select evento_tipo from capital_ledger where operacao_id = :i"),
                {"i": str(op_id)},
            )
            .scalars()
            .all()
        )
        assert sorted(eventos) == ["ativacao_operacao", "baixa_prejuizo"]

        evento = db_session.execute(
            text(
                "select valor, saldo_disponivel_pos from capital_ledger "
                "where operacao_id = :i and evento_tipo = 'baixa_prejuizo'"
            ),
            {"i": str(op_id)},
        ).one()
        assert evento.valor == Decimal("20000.00")
        assert evento.saldo_disponivel_pos == Decimal("30000.00")

    def test_write_off_encolhe_o_teto_de_forma_permanente(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A consequencia intencional, escrita como teste para ninguem a
        "consertar" depois achando que e regressao.

        Com 50.000 de capital e 30.000 baixados como prejuizo, sobram 20.000
        de capacidade — para sempre. Uma nova operacao de 25.000 nao cabe, e
        so um APORTE de capital devolve a capacidade perdida (uma baixa
        contabil nao devolve)."""
        perdida = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, perdida)
        transicionar_operacao(db_session, perdida, "baixada_prejuizo")

        nova = _criar_operacao(db_session, tomador_autorizado, 25_000)
        with pytest.raises(TetoCapitalExcedido) as exc:
            ativar_operacao(db_session, nova)
        assert sqlstate_de(exc.value) == "OC001"

        # Aporte de 30.000 e o unico caminho de volta.
        registrar_evento_capital(db_session, valor=Decimal("30000"), tipo_evento="constituicao")
        assert ativar_operacao(db_session, nova).status == "ativa"

    def test_write_off_e_terminal_nos_dois_sentidos(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Nada sai de 'baixada_prejuizo' (OC003).

        Voltar para 'ativa' ressuscitaria um credito sem contrato; ir para
        'liquidada' devolveria ao teto, em dois passos, o capital que a 017
        recusa devolver em um — e sem passar pelo gate de quitacao, porque
        naquele momento a operacao ja nao estaria em 'ativa'."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "baixada_prejuizo")

        for destino in ("ativa", "liquidada", "inadimplente", "renegociada", "cancelada"):
            with pytest.raises(TransicaoInvalida) as exc:
                transicionar_operacao(db_session, op_id, destino)
            assert sqlstate_de(exc.value) == "OC003", destino

    def test_write_off_de_inadimplente_e_o_caminho_comum(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Na pratica se declara perda DEPOIS de a cobranca falhar, entao o
        caminho que mais roda e inadimplente -> baixada_prejuizo. Como os dois
        estados ja ocupavam o teto, o comprometido nao se mexe — o que muda e
        a operacao sair da regua de cobranca."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 15_000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "inadimplente")
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("15000.00")

        transicionar_operacao(db_session, op_id, "baixada_prejuizo")
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("15000.00")
        assert (
            db_session.execute(
                text("select count(*) from v_aging_operacoes where operacao_id = :i"),
                {"i": str(op_id)},
            ).scalar_one()
            == 0
        )

    def test_reducao_de_capital_conta_o_que_foi_baixado_como_prejuizo(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O furo pelo avesso, que so se fecha em fn_check_reducao_capital.

        Se o gate do OC005 nao contasse 'baixada_prejuizo', bastaria baixar
        30.000 como prejuizo e inserir uma 'reducao' de 30.000 para o
        disponivel voltar ao que era antes de tudo: o capital perdido
        reaparecendo como capacidade de emprestar, com o teto menor no papel.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "baixada_prejuizo")

        with pytest.raises(ReducaoCapitalBloqueada) as exc:
            registrar_evento_capital(db_session, valor=Decimal("30000"), tipo_evento="reducao")
        assert sqlstate_de(exc.value) == "OC005"

    def test_valor_de_operacao_baixada_como_prejuizo_continua_congelado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O congelamento da 015 vale enquanto a operacao ocupa o teto — e a
        baixada como prejuizo ocupa. Sem isto, `update ... set
        valor_principal = 1` devolveria capital ao disponivel sem transicao,
        sem evento e sem erro: o furo desta migration reaberto pela porta que
        a 015 ja sabia ser perigosa."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "baixada_prejuizo")

        exc = _bloqueio(
            db_session,
            "update operacao_credito set valor_principal = 1 where id = :i",
            {"i": str(op_id)},
        )
        assert sqlstate_de(exc) == "OC020"
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")

    def test_exposicao_de_pld_conta_o_que_foi_baixado_como_prejuizo(
        self,
        db_session: Session,
        tomador_sem_identificacao: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """`v_tomadores_sem_identificacao.capital_exposto` (010) tambem passou
        a contar 'baixada_prejuizo'.

        A view responde uma pergunta de PLD (Lei 9.613/98), nao de teto:
        quanto dinheiro esta na rua com gente de quem nao temos identificacao
        arquivada. Perdoar a divida nao desfaz a saida do dinheiro — ao
        contrario, e o caso que mais interessa a uma fiscalizacao. Sem a
        redefinicao da 017, declarar prejuizo ZERAVA a exposicao do tomador na
        unica tela do sistema onde ela aparece.

        O cenario e o real: a evidencia existia na ativacao (OC019 exige) e
        foi expurgada depois de vencida a retencao de 5 anos — que e como um
        tomador com dinheiro na rua acaba dentro desta view.

        DESDE A 022 O EXPURGO EXIGE MAIS DO QUE O PISO VENCIDO, e o cenario
        precisou acompanhar: os 5 anos contam do ENCERRAMENTO da relacao (Lei
        9.613/98, art. 10, III), e a baixa como prejuizo e o encerramento. Sem
        envelhecer esse encerramento o DELETE bate em OC013 — corretamente, e
        essa e a nova regra. O que o teste descreve continua sendo o mesmo
        estado de mundo: dinheiro perdido na rua, evidencia ja expurgada por
        prazo legalmente vencido.
        """
        db_session.execute(
            text(
                "insert into tomador_documento "
                "    (tomador_id, tipo, nome_arquivo, sha256, retencao_ate) "
                "values (:t, 'contrato_social', 'vencido.pdf', :sha, "
                "        current_date - interval '1 day')"
            ),
            {"t": str(tomador_sem_identificacao), "sha": "a" * 64},
        )
        db_session.commit()

        op_id = _criar_operacao(db_session, tomador_sem_identificacao, 20_000)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "baixada_prejuizo")
        envelhecer_encerramento(db_session, op_id, anos=6)

        db_session.execute(
            text("delete from tomador_documento where tomador_id = :t"),
            {"t": str(tomador_sem_identificacao)},
        )
        db_session.commit()

        exposto = db_session.execute(
            text(
                "select capital_exposto from v_tomadores_sem_identificacao " "where tomador_id = :t"
            ),
            {"t": str(tomador_sem_identificacao)},
        ).scalar_one()
        assert exposto == Decimal("20000.00")

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

        # Regularizar um inadimplente e pagar: desde a 017 a quitacao exige a
        # agenda inteira baixada, e o gate vale para os DOIS caminhos de
        # entrada em 'liquidada' (de 'ativa' e de 'inadimplente').
        assert quitar_operacao(db_session, op_id) == 12
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
    """A novacao depois da migration 026: criar a substituta NAO baixa a
    original, e a troca acontece na ATIVACAO da substituta.

    Ate a 026 a original saia do comprometido no ato da chamada e a substituta
    nascia sem ocupar nada — entre os dois atos o teto ficava livre com o
    dinheiro na rua. Agora a original continua no comprometido, no aging e em
    cobranca ate a substituta passar pelos gates de ativacao, e a troca
    (original -> renegociada, substituta -> ativa) acontece num commit so.
    """

    def test_renegociar_direto_e_bloqueado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Marcar 'renegociada' a mao tiraria a original do comprometido sem
        nada entrar no lugar — o furo inteiro em um UPDATE."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)

        with pytest.raises(NovacaoForaDaTransacaoAtomica) as exc:
            transicionar_operacao(db_session, op_id, "renegociada")
        assert sqlstate_de(exc.value) == "OC008"

    def test_novacao_cria_substituta_sem_baixar_a_original(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O teste que ENDOSSAVA o furo, reescrito para a nova realidade.

        Ele afirmava `original == 'renegociada'` e `comprometido == 0` logo
        apos a chamada de novacao — ou seja, afirmava que renegociar libera o
        teto sem um centavo ter voltado. Era a assinatura do defeito escrita
        como expectativa.

        O que a 026 garante: a chamada cria o contrato substituto e mais nada.
        Nenhum capital se move, porque nenhum dinheiro se moveu.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 40000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("40000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )

        original = db_session.execute(
            text("select status from operacao_credito where id = :i"), {"i": str(op_id)}
        ).scalar_one()
        assert original == "ativa", (
            "a original saiu do comprometido no ato da novacao — e nada entrou no lugar, "
            "porque a substituta nasce em 'registrada'."
        )
        assert nova.status == "registrada"
        assert str(nova.substitui_operacao_id) == str(op_id)

        # O teto nao se moveu: e a original que continua ocupando os 40.000.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("40000.00")

        # E ela continua em cobranca — sob o desenho antigo, 'renegociada' saia
        # do aging e a substituta 'registrada' nunca entrava: ninguem cobrava.
        assert (
            db_session.execute(
                text("select count(*) from v_aging_operacoes where operacao_id = :i"),
                {"i": str(op_id)},
            ).scalar_one()
            == 1
        )

    def test_novacao_nao_grava_evento_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A chamada de novacao nao move capital, entao nao tem o que gravar.

        Antes da 026 ela gravava 'renegociacao' na hora — um evento de SAIDA
        de capital para um ato em que nenhum real voltou, e a serie temporal
        do dashboard mostrava capital livre que nao existia.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="SAC",
            numero_parcelas=12,
        )

        eventos = (
            db_session.execute(
                text("select evento_tipo from capital_ledger where operacao_id = :i order by seq"),
                {"i": str(op_id)},
            )
            .scalars()
            .all()
        )
        assert eventos == ["ativacao_operacao"]

    def test_ativar_a_substituta_faz_a_troca_num_commit_so(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A troca: a original sai e a substituta entra no MESMO commit.

        Os dois eventos do ledger contam os dois lados, na ordem em que a
        troca aconteceu. A ordenacao e por `seq` (migration 020) e nao por
        `created_at`: dentro de uma transacao `now()` e o mesmo instante para
        as duas linhas, e ordenar por ele deixaria a prova ao acaso do uuid.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="SAC",
            numero_parcelas=18,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        assert (
            db_session.execute(
                text("select status from operacao_credito where id = :i"), {"i": str(op_id)}
            ).scalar_one()
            == "renegociada"
        )

        eventos = db_session.execute(
            text("select evento_tipo, operacao_id from capital_ledger order by seq")
        ).all()
        assert [(e.evento_tipo, str(e.operacao_id)) for e in eventos] == [
            ("ativacao_operacao", str(op_id)),
            ("renegociacao", str(op_id)),
            ("ativacao_operacao", str(nova.id)),
        ]

        # Um titulo trocado por outro do mesmo valor nao muda o teto.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")

    def test_sem_dupla_contagem_ao_ativar_a_substituta(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O teste central da novacao: 40.000 originais trocados por 40.000
        substitutos NAO podem somar 80.000 de comprometido.

        O risco e o inverso do furo da 026 e nasce do proprio conserto: se a
        original nao saisse do comprometido DENTRO do gate de ativacao, a
        substituta seria somada por cima dela e uma troca pelo mesmo valor
        morreria no teto (OC001) — recusa espuria no caminho feliz mais comum
        da renegociacao.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 40000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("40000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )
        # A substituta é um título novo: precisa do próprio registro.
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("40000.00")

    def test_novacao_de_operacao_nao_renegociavel_e_recusada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """So 'ativa' ou 'inadimplente' podem ser renegociadas."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 5000)  # fica em 'registrada'

        with pytest.raises(TransicaoInvalida):
            novar_operacao(
                db_session,
                op_id,
                valor_principal=Decimal("5000"),
                taxa_juros_mensal=Decimal("1.0"),
                sistema_amortizacao="PRICE",
                numero_parcelas=6,
            )

    def test_novacao_de_inadimplente_e_permitida(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Renegociar um inadimplente e o caso de uso mais comum de novacao —
        e o que mais precisa do gate, porque e onde a tentacao de 'zerar a
        divida no papel' aparece."""
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
        # A original continua inadimplente e continua ocupando o teto: nada
        # foi pago, entao nada foi liberado.
        assert (
            db_session.execute(
                text("select status from operacao_credito where id = :i"), {"i": str(op_id)}
            ).scalar_one()
            == "inadimplente"
        )
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("20000.00")


# ---------------------------------------------------------------------------
# O furo da novacao sem lastro — migration 026
#
# `fn_novar_operacao` (migrations/006:224) aceitava `p_valor_principal`
# arbitrario e nao o confrontava com NADA: nem com o principal da original,
# nem com o que foi efetivamente amortizado contra movimento bancario.
# Renegociar R$ 30.000 por R$ 0,01, com as doze parcelas em aberto e zero
# centavo comprovado, era um `update ... set status='renegociada'` que caia no
# bloco de SAIDA do trigger do teto e devolvia os R$ 30.000 inteiros ao capital
# disponivel.
#
# E EXATAMENTE O EFEITO QUE A 017 RECUSA NO PROPRIO CABECALHO — "liberar teto
# por um emprestimo que nunca foi pago permitiria emprestar de novo o mesmo
# dinheiro que ja se perdeu". A 017 fechou a porta da frente (`liquidar` deixou
# de devolver capital sem a agenda baixada, OC022) e deixou esta aberta: aquele
# gate olha `new.status = 'liquidada'`, e 'renegociada' ficou fora do conjunto
# que ocupa o teto. Mesma perda, mesma devolucao indevida, outro verbo.
#
# Os testes abaixo NAO sao furos diferentes: sao a mesma falha medida em dois
# pontos — no comprometido (o instrumento) e no dinheiro na rua (o fato) — e
# pelas duas portas que a 026 fecha, o VALOR e a JANELA.
# ---------------------------------------------------------------------------


def _principal_na_rua(db_session: Session) -> Decimal:
    """Principal que SAIU do caixa e ainda nao voltou, medido pela agenda.

    Nao pergunta o status da operacao — e justamente o status que o furo
    manipula. Pergunta pela parcela em aberto, que so existe porque a operacao
    foi ATIVADA (a agenda nasce na ativacao, migration 007) e so deixa de estar
    aberta contra movimento bancario (`fn_baixar_parcela`, migration 009). Uma
    operacao com parcela aberta e dinheiro na rua, esteja ela 'ativa',
    'inadimplente' ou carimbada de 'renegociada' por uma substituta de um
    centavo que ninguem chegou a ativar.

    NOTA DE USO, para quem for reaproveitar: a agenda da original NAO e apagada
    quando a novacao se consuma (a 007 a torna imutavel, e ela e a prova
    documental do que foi acordado), entao depois de uma troca CONCLUIDA esta
    funcao conta a original e a substituta juntas. Ela serve para medir o furo
    — cenarios em que a troca NAO se consumou —, nao para auditar o caminho
    feliz.
    """
    return Decimal(
        db_session.execute(
            text(
                """
                select coalesce(sum(o.valor_principal), 0)
                from operacao_credito o
                where exists (
                    select 1 from parcela p
                    where p.operacao_id = o.id and p.status = 'aberta'
                )
                """
            )
        ).scalar_one()
    )


class TestNovacaoSemLastroNaoLiberaTeto:
    """A regra: O COMPROMETIDO NAO PODE DIMINUIR NUMA NOVACAO SEM LASTRO.

    Decorre da politica de liquidacao ja adotada (DECISOES_PENDENTES.md secao
    6): write-off nao devolve capital porque o dinheiro nao voltou. A novacao e
    a mesma pergunta com outra roupa — se o principal nao foi amortizado contra
    movimento bancario, o montante continua consumido pela operacao e a
    substituta tem que cobrir o saldo devedor da original. Reducao so e
    legitima na medida do que foi efetivamente pago; capitalizar juros
    (substituta MAIOR) segue livre, porque o teto e conferido na ativacao dela.
    """

    def test_novacao_por_valor_irrisorio_e_recusada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Renegociar 30.000 por 0,01 com as doze parcelas em aberto.

        Zero centavo comprovado no extrato. Antes da 026 o comprometido caia de
        30.000 para 0 — o banco declarava livre um capital que continuava na
        rua.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")

        # Nenhuma parcela baixada: nada foi amortizado contra movimento bancario.
        abertas = db_session.execute(
            text("select count(*) from parcela where operacao_id = :i and status = 'aberta'"),
            {"i": str(op_id)},
        ).scalar_one()
        assert abertas == 12

        with pytest.raises(NovacaoSemLastro) as exc:
            novar_operacao(
                db_session,
                op_id,
                valor_principal=Decimal("0.01"),
                taxa_juros_mensal=Decimal("2.5"),
                sistema_amortizacao="PRICE",
                numero_parcelas=12,
                registro_entidade_ref="REG-NOVA",
            )
        assert sqlstate_de(exc.value) == "OC024"
        # A mensagem tem que carregar as saidas — um 422 que so diz "nao pode"
        # deixa o operador sem proximo passo.
        assert "baixada_prejuizo" in str(exc.value)

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")
        assert (
            db_session.execute(
                text("select count(*) from operacao_credito where substitui_operacao_id = :i"),
                {"i": str(op_id)},
            ).scalar_one()
            == 0
        ), "a substituta subfaturada foi criada mesmo assim — um contrato que ja nasce impossivel."

    def test_novacao_irrisoria_nao_poe_80_mil_na_rua_sobre_50_mil_de_capital(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A sequencia inteira, toda ela pelo caminho real — ativar, renegociar
        por valor irrisorio, cancelar a substituta, ativar uma nova operacao
        pelo capital inteiro. Sem SQL direto e sem ma-fe aparente.

        Sobre R$ 50.000 de capital social o sistema aceitava R$ 80.000 na rua:
        os 30.000 originais, que ninguem pagou e cuja agenda continua inteira em
        aberto, mais 50.000 novos. E a violacao direta do Art. 5o da LC
        167/2019 — emprestar alem do capital proprio — que o teto existe para
        impedir.

        O teste tolera QUALQUER mecanismo de correcao: envolve a novacao e a
        ativacao em `except` e assere sobre o ESTADO final. Recusar a novacao
        subfaturada satisfaz a lei; aceita-la mantendo o comprometido de pe
        tambem. O que nenhum dos dois pode e terminar com o capital declarado
        livre para emprestar de novo o dinheiro que continua na rua.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)
        assert _principal_na_rua(db_session) == Decimal("30000.00")

        nova = None
        try:
            nova = novar_operacao(
                db_session,
                op_id,
                valor_principal=Decimal("0.01"),
                taxa_juros_mensal=Decimal("2.5"),
                sistema_amortizacao="PRICE",
                numero_parcelas=12,
                registro_entidade_ref="REG-NOVA",
            )
        except RegraNegocioViolada:
            pass

        if nova is not None:
            # A substituta some antes de ser ativada; o teto que a original
            # liberou nao volta com ela.
            transicionar_operacao(db_session, nova.id, "cancelada")

        outra = _criar_operacao(db_session, tomador_autorizado, 50000)
        try:
            ativar_operacao(db_session, outra)
        except TetoCapitalExcedido:
            # O teto recusando a segunda operacao e o desfecho correto.
            pass

        capital = consultar_capital_snapshot(db_session)
        assert _principal_na_rua(db_session) <= Decimal("50000.00")
        assert capital.comprometido <= Decimal("50000.00")
        assert capital.disponivel >= Decimal("0")

    def test_cancelar_a_substituta_nao_libera_o_teto(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A JANELA, isolada do valor: a substituta cobre o saldo devedor
        inteiro e mesmo assim e cancelada antes de ativar.

        Era o segundo lado do mesmo furo — a substituta nascia em 'registrada',
        que nao ocupa o teto, enquanto a original saia do comprometido no MESMO
        comando, sem prazo para ativar a substituta. Bastava novar pelo valor
        cheio e cancelar para liberar 30.000 com o dinheiro na rua. Corrigir so
        o valor deixaria esta porta aberta.

        Com o desenho da 026, cancelar a substituta e INOFENSIVO e nao precisou
        de regra nova: a original nunca chegou a sair.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )
        transicionar_operacao(db_session, nova.id, "cancelada")

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")
        assert (
            db_session.execute(
                text("select status from operacao_credito where id = :i"), {"i": str(op_id)}
            ).scalar_one()
            == "ativa"
        )
        # E a divida velha continua exigivel — ninguem parou de cobrar.
        assert (
            db_session.execute(
                text("select count(*) from v_aging_operacoes where operacao_id = :i"),
                {"i": str(op_id)},
            ).scalar_one()
            == 1
        )

    def test_substituta_encolhida_depois_de_criada_e_recusada_na_ativacao(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Por que o gate de valor e conferido DUAS vezes.

        A 015 congela os campos economicos de quem OCUPA o teto — e uma
        substituta pendente esta em 'registrada', que nao ocupa. Novar pelo
        valor cheio e depois `update ... set valor_principal = 0.01` na
        substituta reabriria o furo inteiro por uma linha de SQL, se a
        conferencia so existisse no momento da novacao.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)

        db_session.execute(
            text("update operacao_credito set valor_principal = 0.01 where id = :i"),
            {"i": str(nova.id)},
        )
        db_session.commit()

        with pytest.raises(NovacaoSemLastro) as exc:
            ativar_operacao(db_session, nova.id)
        assert sqlstate_de(exc.value) == "OC024"

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")
        assert (
            db_session.execute(
                text("select status from operacao_credito where id = :i"), {"i": str(op_id)}
            ).scalar_one()
            == "ativa"
        )

    def test_substituta_orfa_nao_pode_ser_ativada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A original saiu do comprometido por outro caminho: nao ha lugar a
        ceder, e ativar a substituta seria credito NOVO com nome de novacao.

        Aqui a original e quitada com lastro entre a novacao e a ativacao —
        caminho perfeitamente legitimo, que devolve os 30.000 ao teto. A
        substituta, se ativada em cima disso, somaria 30.000 por fora da conta
        que o teto faz.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)

        assert quitar_operacao(db_session, op_id) == 12
        transicionar_operacao(db_session, op_id, "liquidada")
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")

        with pytest.raises(NovacaoSemLastro) as exc:
            ativar_operacao(db_session, nova.id)
        assert sqlstate_de(exc.value) == "OC024"
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")

    def test_substituta_de_original_baixada_como_prejuizo_e_recusada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O OUTRO subcaso da orfa, e o unico em que a original recusada AINDA
        OCUPA o teto — por isso ele existe separado do teste acima.

        'baixada_prejuizo' esta no conjunto do comprometido desde a 017: e
        disso que depende a regra de que write-off nao devolve capital. Aqui a
        recusa nao e por falta de lugar a ceder, e pelo contrario — a perda ja
        foi reconhecida, os 20.000 seguem consumindo o teto e nao voltam, e
        ativar a substituta ressuscitaria como titulo novo uma divida morta,
        somando o mesmo dinheiro duas vezes (20.000 de prejuizo + 20.000 de
        substituta = 40.000 sobre 20.000 que sairam do caixa uma vez so).

        A MENSAGEM E PARTE DO INVARIANTE: um 422 que dissesse a este operador
        que a original 'ja nao ocupa o teto' estaria mentindo sobre o motivo da
        recusa e o mandaria procurar o erro no lugar errado.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 20000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("20000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)

        transicionar_operacao(db_session, op_id, "baixada_prejuizo")
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("20000.00")

        with pytest.raises(NovacaoSemLastro) as exc:
            ativar_operacao(db_session, nova.id)
        assert sqlstate_de(exc.value) == "OC024"
        assert "baixada como prejuízo" in str(exc.value)
        assert "já não ocupa o teto" not in str(exc.value)

        # O prejuizo continua consumindo o teto, e nada entrou em cima dele.
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("20000.00")
        assert (
            db_session.execute(
                text("select status from operacao_credito where id = :i"), {"i": str(nova.id)}
            ).scalar_one()
            == "registrada"
        )

    def test_segunda_substituta_pendente_e_recusada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Duas substitutas pendentes sobre a mesma original seriam duas trocas
        pelo mesmo lugar: ativada a primeira, a segunda viraria dinheiro novo.

        OC003 e nao OC024: aqui nao falta lastro, falta resolver um conflito de
        estado — e ele se resolve cancelando a pendente, coisa que a 026 tornou
        inofensiva.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        primeira = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )

        with pytest.raises(TransicaoInvalida) as exc:
            novar_operacao(
                db_session,
                op_id,
                valor_principal=Decimal("30000"),
                taxa_juros_mensal=Decimal("2.0"),
                sistema_amortizacao="SAC",
                numero_parcelas=18,
                registro_entidade_ref="REG-NOVA-2",
            )
        assert sqlstate_de(exc.value) == "OC003"

        # Cancelada a pendente, renegociar de novo volta a ser possivel.
        transicionar_operacao(db_session, primeira.id, "cancelada")
        segunda = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="SAC",
            numero_parcelas=18,
            registro_entidade_ref="REG-NOVA-2",
        )
        assert segunda.status == "registrada"


def _amortizado_com_lastro(db_session: Session, operacao_id: uuid.UUID) -> Decimal:
    """Principal ja devolvido: soma de `valor_amortizacao` das parcelas pagas
    COM movimento bancario — a mesma conta de `fn_saldo_devedor_com_lastro`.

    Lida do banco em vez de escrita a mao no teste porque a decomposicao
    PRICE/SAC e do gerador de agenda (007): um numero fixo aqui provaria a
    aritmetica do teste, nao a do sistema. E e justamente essa decomposicao que
    o gate depende — usar `valor_total` creditaria juros como principal.
    """
    return Decimal(
        db_session.execute(
            text(
                "select coalesce(sum(valor_amortizacao), 0) from parcela "
                "where operacao_id = :i and status = 'paga' and movimento_id is not null"
            ),
            {"i": str(operacao_id)},
        ).scalar_one()
    )


class TestRenegociacaoLegitimaContinuaFuncionando:
    """O caminho feliz, que importa tanto quanto o gate.

    Renegociar e operacao LEGITIMA e frequente — e o instrumento normal para
    tratar um tomador em dificuldade. Um gate que so soubesse dizer "nao"
    empurraria a ESC para a unica alternativa que sobra, que e a inadimplencia
    seguida de write-off: pior para o tomador, pior para o capital e pior para
    o balanco. Os quatro casos abaixo sao os que precisam continuar passando.
    """

    def test_alongar_prazo_pelo_mesmo_valor(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O caso mais comum: mesma divida, mais parcelas, prestacao menor.
        Nao move um centavo de principal e nao pode ser recusado."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=36,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        assert nova.numero_parcelas == 36
        assert (
            len(
                db_session.execute(
                    text("select id from parcela where operacao_id = :i"), {"i": str(nova.id)}
                ).all()
            )
            == 36
        )
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")

    def test_mudar_a_taxa_pelo_mesmo_valor(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Reduzir juros e concessao sobre RECEITA FUTURA, nao sobre principal:
        o dinheiro na rua e o mesmo, e o teto nao tem por que se mover."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("30000"),
            taxa_juros_mensal=Decimal("0.8"),
            sistema_amortizacao="PRICE",
            numero_parcelas=12,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        assert nova.taxa_juros_mensal == Decimal("0.80")
        assert consultar_capital_snapshot(db_session).comprometido == Decimal("30000.00")

    def test_capitalizar_juros_substituta_maior(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Incorporar juros vencidos ao principal: a substituta e MAIOR que a
        original, e isso continua livre.

        O gate da 026 e um PISO, nao um teto — quem cuida do lado de cima e o
        gate do Art. 5o, conferido na ativacao da substituta como em qualquer
        outra: os 34.000 cabem nos 50.000 de capital porque a original saiu do
        comprometido no mesmo commit.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("34000"),
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=24,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        capital = consultar_capital_snapshot(db_session)
        assert capital.comprometido == Decimal("34000.00")
        assert capital.disponivel == Decimal("16000.00")

    def test_reducao_na_medida_exata_do_que_foi_amortizado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A substituta PODE ser menor — na medida do principal efetivamente
        devolvido, e nem um centavo alem.

        Tres das doze parcelas baixadas contra movimento bancario. O piso e o
        principal amortizado, medido por `valor_amortizacao`: usar o valor
        cheio da parcela creditaria os juros como se fossem devolucao de
        principal e deixaria a substituta descer mais do que o tomador pagou —
        que e o furo, em versao proporcional.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30000)
        ativar_operacao(db_session, op_id)
        baixar_parcelas(db_session, op_id, [1, 2, 3])

        amortizado = _amortizado_com_lastro(db_session, op_id)
        saldo_devedor = Decimal("30000.00") - amortizado
        pago_com_juros = Decimal(
            db_session.execute(
                text(
                    "select coalesce(sum(valor_total), 0) from parcela "
                    "where operacao_id = :i and status = 'paga'"
                ),
                {"i": str(op_id)},
            ).scalar_one()
        )
        # O cenario so prova algo se as duas medidas divergirem: e a diferenca
        # entre elas que o gate tem que respeitar.
        assert Decimal("0") < amortizado < pago_com_juros

        # Um centavo abaixo do saldo devedor ainda e recusado.
        with pytest.raises(NovacaoSemLastro) as exc:
            novar_operacao(
                db_session,
                op_id,
                valor_principal=saldo_devedor - Decimal("0.01"),
                taxa_juros_mensal=Decimal("2.5"),
                sistema_amortizacao="PRICE",
                numero_parcelas=12,
                registro_entidade_ref="REG-NOVA",
            )
        assert sqlstate_de(exc.value) == "OC024"

        # No saldo devedor exato, passa — e a troca devolve ao teto exatamente
        # o que foi pago, nem mais nem menos.
        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=saldo_devedor,
            taxa_juros_mensal=Decimal("2.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=12,
            registro_entidade_ref="REG-NOVA",
        )
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        capital = consultar_capital_snapshot(db_session)
        assert capital.comprometido == saldo_devedor
        assert capital.disponivel == Decimal("50000.00") - saldo_devedor


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
        quitar_operacao(db_session, op_id)

        transicionar_operacao(db_session, op_id, "liquidada")

        assert consultar_capital_snapshot(db_session).comprometido == Decimal("0")

    def test_novacao_continua_sendo_o_caminho_para_mudar_valor(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """Caminho feliz que fecha o argumento: o congelamento nao impede
        renegociar, so obriga a fazer pela porta que amarra a substituta a
        original sob o mesmo lock, na mesma transacao.

        A substituta e MAIOR que a original (capitalizacao de juros): desde a
        migration 026 ela nao pode ser menor que o saldo devedor com lastro, e
        aqui nada foi amortizado. O ponto do teste continua sendo o mesmo — o
        valor economico da operacao muda por novacao, nunca por UPDATE."""
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        nova = novar_operacao(
            db_session,
            op_id,
            valor_principal=Decimal("32000"),
            taxa_juros_mensal=Decimal("1.5"),
            sistema_amortizacao="PRICE",
            numero_parcelas=18,
        )

        assert nova.valor_principal == Decimal("32000.00")
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
