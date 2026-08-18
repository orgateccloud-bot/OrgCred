"""
Apuração fiscal no Lucro Presumido (migrations 011 e 018) contra Postgres real.

A 011 trouxe a arquitetura: cálculo dentro do banco, apuração imutável com
retificação por versão, snapshot dos parâmetros e recusa (OC015) quando não há
parâmetro. As duas coisas que este arquivo travava desde então:

1. Que a base seja SÓ O JURO. Somar amortização — devolução de principal —
   inflaria a tributação em várias vezes sobre dinheiro que não é resultado.
2. Que sem parâmetro configurado a apuração RECUSE, em vez de devolver um
   número plausível calculado com alíquota inventada pelo sistema.

A 018 corrigiu o CONTEÚDO tributário, e as classes do fim deste arquivo travam
os quatro pontos que passavam verdes porque a suíte só exercitava o cenário
limpo — uma operação, um parâmetro, tudo no mesmo trimestre:

3. QUAL parâmetro se aplica (o do período apurado, não o de hoje);
4. QUAIS agendas entram na competência (não as duas de uma novação);
5. QUAL data ancora o caixa (a do extrato, não a da conciliação);
6. Que mora e multa recebidas não sumam da base — subdeclaração é o lado do
   erro que gera multa de ofício.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import (
    ativar_operacao,
    baixar_parcela,
    novar_operacao,
    registrar_movimento_bancario,
)
from app.core.security import get_admin_user, get_current_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.conftest import confirmar_registro, quitar_operacao, sqlstate_de


# Valores de teste, escolhidos por serem fáceis de conferir a olho — NÃO são
# recomendação tributária. As alíquotas reais são configuração do contador,
# e é justamente por isso que nada vem semeado no banco.
PARAMETROS = {
    "vigencia_inicio": "2020-01-01",
    "percentual_presuncao_irpj": "0.32",
    "percentual_presuncao_csll": "0.32",
    "aliquota_irpj": "0.15",
    "aliquota_csll": "0.09",
    "adicional_irpj_aliquota": "0.10",
    "adicional_irpj_limite": "60000.00",
    "aliquota_pis": "0.0065",
    "aliquota_cofins": "0.03",
    "regime_reconhecimento": "competencia",
}


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(client: TestClient) -> TestClient:
    admin = Usuario(
        id=uuid.uuid4(), email="admin@orgatec.com", nome="Admin", papel="admin", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_admin_user] = lambda: admin
    return client


@pytest.fixture()
def operador_client(client: TestClient) -> TestClient:
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Op", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    return client


def _operacao_com_agenda(
    db_session: Session, tomador_id: uuid.UUID, valor: str = "12000", taxa: str = "2.0"
) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', :v, :taxa, 'PRICE', 12, 'registrada', 'REG-FISCAL')
        returning id
        """),
        {"t": str(tomador_id), "v": valor, "taxa": taxa},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)
    return op_id


def _trimestre_da_parcela(db_session: Session, op_id: uuid.UUID, numero: int) -> tuple[int, int]:
    venc = db_session.execute(
        text("select vencimento from parcela where operacao_id = :o and numero = :n"),
        {"o": str(op_id), "n": numero},
    ).scalar_one()
    return venc.year, (venc.month - 1) // 3 + 1


def _janela(ano: int, trimestre: int) -> tuple[date, date]:
    """Primeiro dia do trimestre e primeiro dia do trimestre seguinte.

    Mesma aritmética de fn_apurar_trimestre — meio-aberta à direita, para que
    o teste some exatamente as parcelas que o banco somaria.
    """
    inicio = date(ano, (trimestre - 1) * 3 + 1, 1)
    fim = date(ano + (trimestre // 4), (trimestre % 4) * 3 + 1, 1)
    return inicio, fim


def _juros_da_operacao_no_trimestre(
    db_session: Session, op_id: uuid.UUID, ano: int, trimestre: int
) -> Decimal:
    """Juros contratuais que a agenda DESTA operação acumula no trimestre."""
    inicio, fim = _janela(ano, trimestre)
    return db_session.execute(  # type: ignore[no-any-return]
        text("""
        select coalesce(sum(valor_juros), 0)
        from parcela
        where operacao_id = :op and vencimento >= :inicio and vencimento < :fim
        """),
        {"op": str(op_id), "inicio": inicio, "fim": fim},
    ).scalar_one()


def _juros_de_todas_as_agendas_no_trimestre(
    db_session: Session, ano: int, trimestre: int
) -> Decimal:
    """Soma cega, sem olhar a operação dona da parcela — o cálculo ERRADO que
    a 011 fazia no regime de competência. Serve de contraprova: o número
    apurado tem que ficar ABAIXO deste quando há agenda renegociada no banco."""
    inicio, fim = _janela(ano, trimestre)
    return db_session.execute(  # type: ignore[no-any-return]
        text("""
        select coalesce(sum(valor_juros), 0)
        from parcela
        where vencimento >= :inicio and vencimento < :fim
        """),
        {"inicio": inicio, "fim": fim},
    ).scalar_one()


def _antecipar_vencimento(db_session: Session, op_id: uuid.UUID, numero: int, dias: int) -> date:
    """Puxa o vencimento de UMA parcela para `dias` atrás e devolve a data.

    Existe para fabricar o único cenário que prova o lado "a receita anterior
    ao corte FICA" da migration 018: uma parcela que já venceu ANTES de a
    operação ser novada ou baixada como prejuízo. Pelo caminho normal ele é
    inalcançável em teste — a agenda nasce na ativação com o primeiro
    vencimento um mês à frente, então toda parcela vence depois de qualquer
    ato praticado no mesmo dia, e o corte por data nunca é exercitado.

    Vencimento é imutável (OC009); o trigger é desligado só neste ponto, como
    já faz `_envelhecer` em tests/test_aging.py. Não poder fazer isso pela API
    é justamente a garantia que a 007 introduziu.

    A referência é `current_date` DO BANCO, não `date.today()` do host: o corte
    é comparado contra `operacao_evento.created_at`, que é relógio do Postgres.
    Ancorar no host faz o teste errar um dia sempre que as duas máquinas
    estiverem em fusos diferentes — é o flake que hoje derruba
    tests/test_aging.py depois das 21h locais.
    """
    hoje_no_banco: date = db_session.execute(text("select current_date")).scalar_one()
    vencimento = hoje_no_banco - timedelta(days=dias)

    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    db_session.execute(
        text("update parcela set vencimento = :v where operacao_id = :op and numero = :n"),
        {"v": vencimento, "op": str(op_id), "n": numero},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()
    return vencimento


def _juros_da_parcela(db_session: Session, op_id: uuid.UUID, numero: int) -> Decimal:
    return db_session.execute(  # type: ignore[no-any-return]
        text("select valor_juros from parcela where operacao_id = :op and numero = :n"),
        {"op": str(op_id), "n": numero},
    ).scalar_one()


def _trimestre_de(data: date) -> tuple[int, int]:
    return data.year, (data.month - 1) // 3 + 1


def _meses_atras(referencia: date, meses: int) -> date:
    """Mesma data, `meses` meses antes, no dia 15 — longe de fim de mês para
    não depender do tamanho do mês de destino."""
    total = referencia.year * 12 + (referencia.month - 1) - meses
    return date(total // 12, total % 12 + 1, 15)


# ---------------------------------------------------------------------
# Parâmetros
# ---------------------------------------------------------------------


class TestParametros:
    def test_sem_configuracao_o_vigente_e_nulo(self, admin_client: TestClient) -> None:
        """A tela precisa distinguir 'não configurado' de 'erro ao carregar'."""
        assert admin_client.get("/api/fiscal/parametros/vigente").json() is None
        assert admin_client.get("/api/fiscal/parametros").json() == []

    def test_registrar_e_ler_vigente(self, admin_client: TestClient) -> None:
        assert admin_client.post("/api/fiscal/parametros", json=PARAMETROS).status_code == 201

        vigente = admin_client.get("/api/fiscal/parametros/vigente").json()
        assert Decimal(vigente["aliquota_irpj"]) == Decimal("0.15")
        assert vigente["regime_reconhecimento"] == "competencia"

    def test_vigencia_mais_recente_vence(self, admin_client: TestClient) -> None:
        """Alíquota muda por lei: o histórico fica, e o vigente é o mais
        recente que já entrou em vigor."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        novo = {**PARAMETROS, "vigencia_inicio": "2024-01-01", "aliquota_irpj": "0.20"}
        admin_client.post("/api/fiscal/parametros", json=novo)

        assert Decimal(
            admin_client.get("/api/fiscal/parametros/vigente").json()["aliquota_irpj"]
        ) == Decimal("0.20")
        assert len(admin_client.get("/api/fiscal/parametros").json()) == 2

    def test_vigencia_futura_nao_vale_ainda(self, admin_client: TestClient) -> None:
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        futuro = {**PARAMETROS, "vigencia_inicio": "2199-01-01", "aliquota_irpj": "0.99"}
        admin_client.post("/api/fiscal/parametros", json=futuro)

        assert Decimal(
            admin_client.get("/api/fiscal/parametros/vigente").json()["aliquota_irpj"]
        ) == Decimal("0.15")

    def test_percentual_em_pontos_percentuais_e_recusado(self, admin_client: TestClient) -> None:
        """Aceitar "15" e "0,15" na mesma API é como se escreve um erro de
        duas ordens de grandeza numa base tributária."""
        errado = {**PARAMETROS, "aliquota_irpj": "15"}
        assert admin_client.post("/api/fiscal/parametros", json=errado).status_code == 422

    def test_vigencia_duplicada_e_recusada(self, admin_client: TestClient) -> None:
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        repetido = admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        assert repetido.status_code == 422
        assert "Já existe parâmetro" in repetido.json()["detail"]

    def test_operador_nao_configura_parametros(self, operador_client: TestClient) -> None:
        assert operador_client.post("/api/fiscal/parametros", json=PARAMETROS).status_code == 403


# ---------------------------------------------------------------------
# Apuração
# ---------------------------------------------------------------------


class TestApuracao:
    def test_sem_parametro_recusa(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Recusar é a única resposta honesta: calcular com alíquota
        embutida no código produziria um valor plausível e errado."""
        _operacao_com_agenda(db_session, tomador_autorizado)

        resposta = admin_client.post("/api/fiscal/apuracoes", json={"ano": 2026, "trimestre": 1})
        assert resposta.status_code == 422
        assert resposta.json()["codigo"] == "OC015"

    def test_base_e_so_o_juro(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A amortização devolve principal e não é resultado. Se entrasse na
        base, a tributação seria várias vezes maior."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)

        inicio = date(ano, (trimestre - 1) * 3 + 1, 1)
        esperado = db_session.execute(
            text("""
            select coalesce(sum(valor_juros), 0), coalesce(sum(valor_amortizacao), 0)
            from parcela
            where vencimento >= :inicio and vencimento < :fim
            """),
            {"inicio": inicio, "fim": date(ano + (trimestre // 4), (trimestre % 4) * 3 + 1, 1)},
        ).one()
        juros_periodo, amortizacao_periodo = esperado

        corpo = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()

        assert Decimal(corpo["receita_juros"]) == juros_periodo
        assert amortizacao_periodo > 0  # havia amortização no período...
        assert Decimal(corpo["receita_juros"]) < amortizacao_periodo  # ...e ficou de fora

    def test_calculo_completo(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)

        c = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        receita = Decimal(c["receita_juros"])

        assert Decimal(c["base_irpj"]) == round(receita * Decimal("0.32"), 2)
        assert Decimal(c["irpj"]) == round(Decimal(c["base_irpj"]) * Decimal("0.15"), 2)
        assert Decimal(c["csll"]) == round(Decimal(c["base_csll"]) * Decimal("0.09"), 2)
        # PIS/COFINS cumulativos incidem sobre a RECEITA, não sobre a base
        # presumida — presunção é conceito de IRPJ/CSLL.
        assert Decimal(c["pis"]) == round(receita * Decimal("0.0065"), 2)
        assert Decimal(c["cofins"]) == round(receita * Decimal("0.03"), 2)
        assert Decimal(c["total_tributos"]) == (
            Decimal(c["irpj"])
            + Decimal(c["adicional_irpj"])
            + Decimal(c["csll"])
            + Decimal(c["pis"])
            + Decimal(c["cofins"])
        )

    def test_adicional_so_incide_acima_do_limite(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Receita pequena não paga adicional — se pagasse, toda ESC
        iniciante seria sobretributada."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)

        c = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        assert Decimal(c["base_irpj"]) < Decimal("60000.00")
        assert Decimal(c["adicional_irpj"]) == Decimal("0.00")

    def test_trimestre_sem_movimento_apura_zero(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        """Zero é resultado legítimo, não erro: um trimestre sem receita
        precisa ter apuração para o histórico ficar completo."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)

        c = admin_client.post("/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 2}).json()
        assert Decimal(c["receita_juros"]) == Decimal("0.00")
        assert Decimal(c["total_tributos"]) == Decimal("0.00")

    def test_regime_caixa_so_conta_o_que_foi_recebido(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """No caixa, só o que foi efetivamente recebido entra — e o que
        entra é o que tem lastro bancário (migration 009).

        Aqui o crédito e a conciliação caem no mesmo dia, que é o caso em que
        as duas datas candidatas a âncora coincidem. QUAL das duas o banco usa
        quando elas divergem é assunto de
        TestAncoraDoRegimeDeCaixa.test_trimestre_e_o_do_credito_bancario.
        """
        admin_client.post(
            "/api/fiscal/parametros", json={**PARAMETROS, "regime_reconhecimento": "caixa"}
        )
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        hoje = date.today()
        trimestre_hoje = (hoje.month - 1) // 3 + 1

        # Nada baixado ainda: no caixa, receita zero.
        antes = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": hoje.year, "trimestre": trimestre_hoje}
        ).json()
        assert Decimal(antes["receita_juros"]) == Decimal("0.00")

        parcela = db_session.execute(
            text(
                "select id, valor_total, valor_juros from parcela where operacao_id = :o and numero = 1"
            ),
            {"o": str(op_id)},
        ).one()
        movimento = registrar_movimento_bancario(
            db_session,
            data_movimento=hoje,
            valor=parcela.valor_total,
            documento="FITID-FISCAL",
        )
        baixar_parcela(db_session, parcela.id, movimento)

        depois = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": hoje.year, "trimestre": trimestre_hoje}
        ).json()
        assert Decimal(depois["receita_juros"]) == parcela.valor_juros
        assert depois["versao"] == 2

    def test_reapurar_cria_nova_versao(
        self, admin_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Retificação existe no mundo real. Editar a apuração original
        apagaria o que já foi declarado."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)

        primeira = admin_client.post("/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1})
        segunda = admin_client.post("/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1})
        assert primeira.json()["versao"] == 1
        assert segunda.json()["versao"] == 2

        # A tela mostra só a última...
        vigentes = admin_client.get("/api/fiscal/apuracoes").json()
        assert [a["versao"] for a in vigentes if a["ano"] == 2021 and a["trimestre"] == 1] == [2]
        # ...e as duas continuam no banco.
        assert (
            db_session.execute(
                text("select count(*) from apuracao_fiscal where ano = 2021 and trimestre = 1")
            ).scalar_one()
            == 2
        )

    def test_apuracao_e_imutavel(
        self, admin_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        admin_client.post("/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1})

        with pytest.raises(Exception) as exc:
            db_session.execute(text("update apuracao_fiscal set irpj = 0"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC016"
        db_session.rollback()

        with pytest.raises(Exception) as exc:
            db_session.execute(text("delete from apuracao_fiscal"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC016"
        db_session.rollback()

    def test_parametros_ficam_congelados_na_apuracao(
        self, admin_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """O snapshot é o que torna o número reproduzível: se a apuração
        guardasse só a FK, mudar o parâmetro mudaria uma declaração passada."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        admin_client.post("/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1})

        admin_client.post(
            "/api/fiscal/parametros",
            json={**PARAMETROS, "vigencia_inicio": "2024-01-01", "aliquota_irpj": "0.25"},
        )

        congelado = db_session.execute(
            text("select aliquota_irpj from apuracao_fiscal where ano = 2021 and trimestre = 1")
        ).scalar_one()
        assert congelado == Decimal("0.1500")

    def test_operador_nao_apura(self, operador_client: TestClient) -> None:
        resposta = operador_client.post("/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1})
        assert resposta.status_code == 403

    def test_trimestre_invalido_e_recusado(self, admin_client: TestClient) -> None:
        assert (
            admin_client.post(
                "/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 5}
            ).status_code
            == 422
        )


# ---------------------------------------------------------------------
# (a) Qual parâmetro se aplica — migration 018
# ---------------------------------------------------------------------


class TestParametroDoPeriodoApurado:
    """A 011 lia `v_parametro_fiscal_vigente`, que é ancorada em current_date.

    Apurar 2021 depois de a alíquota ter mudado em 2024 aplicava a alíquota de
    2024 a uma receita de 2021 — e o snapshot gravava o número errado como se
    fosse o do período. O caso que quebrava é o mais comum de todos:
    RETIFICAÇÃO, que por definição se faz depois, quando a lei já mudou.
    """

    def test_trimestre_passado_usa_o_parametro_da_epoca(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """O BLOQUEIO. Duas vigências no banco, a segunda já em vigor hoje: a
        apuração de um trimestre coberto pela PRIMEIRA tem que sair com os
        números da primeira."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        admin_client.post(
            "/api/fiscal/parametros",
            json={**PARAMETROS, "vigencia_inicio": "2024-01-01", "aliquota_irpj": "0.25"},
        )

        corpo = admin_client.post("/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1})
        assert corpo.status_code == 201

        congelado = db_session.execute(
            text("select aliquota_irpj from apuracao_fiscal where ano = 2021 and trimestre = 1")
        ).scalar_one()
        assert congelado == Decimal("0.1500")

    def test_trimestre_posterior_a_mudanca_usa_o_parametro_novo(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """O CAMINHO FELIZ do outro lado: ancorar no período não pode ter
        congelado a apuração no parâmetro mais antigo."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        admin_client.post(
            "/api/fiscal/parametros",
            json={**PARAMETROS, "vigencia_inicio": "2024-01-01", "aliquota_irpj": "0.25"},
        )

        assert (
            admin_client.post(
                "/api/fiscal/apuracoes", json={"ano": 2024, "trimestre": 2}
            ).status_code
            == 201
        )
        congelado = db_session.execute(
            text("select aliquota_irpj from apuracao_fiscal where ano = 2024 and trimestre = 2")
        ).scalar_one()
        assert congelado == Decimal("0.2500")

    def test_vigencia_que_comeca_no_meio_do_trimestre_vale_para_ele_inteiro(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """A âncora é o ENCERRAMENTO do trimestre, não o início.

        No Lucro Presumido o fato gerador se completa no último dia do
        período (Lei 9.430/96, art. 1º). Uma alíquota que entra em vigor em
        15/05 alcança o 2º trimestre inteiro — é a única situação em que as
        duas âncoras candidatas discordam, e por isso a que precisa de teste.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        admin_client.post(
            "/api/fiscal/parametros",
            json={**PARAMETROS, "vigencia_inicio": "2022-05-15", "aliquota_irpj": "0.25"},
        )

        admin_client.post("/api/fiscal/apuracoes", json={"ano": 2022, "trimestre": 2})
        assert db_session.execute(
            text("select aliquota_irpj from apuracao_fiscal where ano = 2022 and trimestre = 2")
        ).scalar_one() == Decimal("0.2500")

        # ...e o trimestre que se encerrou ANTES dela continua com a antiga.
        admin_client.post("/api/fiscal/apuracoes", json={"ano": 2022, "trimestre": 1})
        assert db_session.execute(
            text("select aliquota_irpj from apuracao_fiscal where ano = 2022 and trimestre = 1")
        ).scalar_one() == Decimal("0.1500")

    def test_periodo_anterior_a_qualquer_vigencia_e_recusado(
        self, admin_client: TestClient
    ) -> None:
        """Consequência deliberada: um trimestre que nenhum parâmetro cobre
        deixa de "funcionar" com o parâmetro de hoje e passa a ser recusado.

        Mesma resposta honesta que a 011 já dava para a ausência total de
        parâmetro, e mesmo SQLSTATE — a providência é a mesma: cadastrar a
        vigência que cobre o período.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # vigência 2020-01-01

        resposta = admin_client.post("/api/fiscal/apuracoes", json={"ano": 2019, "trimestre": 4})
        assert resposta.status_code == 422
        assert resposta.json()["codigo"] == "OC015"


# ---------------------------------------------------------------------
# (b) Competência e a agenda renegociada — migration 018
# ---------------------------------------------------------------------


class TestCompetenciaEAgendaRenegociada:
    """A agenda é imutável (007) e NÃO é apagada na novação: fn_novar_operacao
    põe a original em 'renegociada' e cria a substituta com agenda própria.

    A 011 somava `valor_juros` de toda parcela do período, sem olhar a operação
    dona — a partir da primeira novação, todo trimestre somava a agenda morta
    com a viva e a base inflava cumulativamente.
    """

    def test_novacao_nao_soma_as_duas_agendas(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # competência
        original = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, original, 1)

        nova = novar_operacao(
            db_session,
            original,
            valor_principal=Decimal("12000"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="PRICE",
            numero_parcelas=12,
        )
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        juros_substituta = _juros_da_operacao_no_trimestre(db_session, nova.id, ano, trimestre)
        juros_das_duas = _juros_de_todas_as_agendas_no_trimestre(db_session, ano, trimestre)

        # O cenário só prova algo se as duas agendas de fato coexistirem no
        # trimestre: sem isso o teste passaria por vacuidade.
        assert juros_substituta > 0
        assert juros_das_duas > juros_substituta

        corpo = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()

        # O BLOQUEIO: a agenda renegociada ficou de fora...
        assert Decimal(corpo["receita_juros"]) < juros_das_duas
        # ...e o CAMINHO FELIZ: a agenda viva entrou inteira.
        assert Decimal(corpo["receita_juros"]) == juros_substituta

    def test_operacao_baixada_como_prejuizo_para_de_gerar_receita(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Write-off (017): a cobrança encerra e as parcelas ficam 'aberta'
        para sempre, por decisão explícita daquela migration.

        Continuar acumulando competência sobre elas faria a base crescer
        indefinidamente sobre dinheiro que o próprio sistema já registrou como
        perdido.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # competência
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)

        antes = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        assert Decimal(antes["receita_juros"]) > 0  # a agenda viva gerava receita

        db_session.execute(
            text("update operacao_credito set status = 'baixada_prejuizo' where id = :id"),
            {"id": str(op_id)},
        )
        db_session.commit()

        depois = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        # As parcelas vencem DEPOIS do write-off (a agenda começa um mês após a
        # ativação), então nenhuma delas acumulou receita antes do corte.
        assert Decimal(depois["receita_juros"]) == Decimal("0.00")

    def test_receita_anterior_a_novacao_permanece_na_base(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O corte da novação é por DATA, não só por status.

        Um filtro `status in ('ativa','inadimplente','liquidada')` — sem a data
        — conserta a dupla contagem e cria um erro novo do lado caro: apaga
        RETROATIVAMENTE os juros que a agenda original acumulou enquanto estava
        viva. Uma retificação do trimestre antigo passaria a mostrar receita
        MENOR que a declaração original, que é subdeclaração autoinfligida.

        Sem este teste o corte por data não era exercitado por nada: removê-lo
        inteiro deixava as 29 verificações deste arquivo verdes.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # competência
        original = _operacao_com_agenda(db_session, tomador_autorizado)

        # A parcela 1 venceu MUITO antes da novação — 200 dias garante que ela
        # caia num trimestre onde nenhuma outra parcela (nem da original, nem da
        # substituta, todas no futuro) tem vencimento.
        vencida = _antecipar_vencimento(db_session, original, numero=1, dias=200)
        ano, trimestre = _trimestre_de(vencida)
        juros_auferidos = _juros_da_parcela(db_session, original, numero=1)
        assert juros_auferidos > 0

        nova = novar_operacao(
            db_session,
            original,
            valor_principal=Decimal("12000"),
            taxa_juros_mensal=Decimal("2.0"),
            sistema_amortizacao="PRICE",
            numero_parcelas=12,
        )
        confirmar_registro(db_session, nova.id)
        ativar_operacao(db_session, nova.id)

        # O trimestre antigo tem exatamente aquela parcela e mais nada: se
        # tivesse outra, o número abaixo não isolaria o que se quer provar.
        assert (
            _juros_de_todas_as_agendas_no_trimestre(db_session, ano, trimestre) == juros_auferidos
        )

        corpo = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        assert Decimal(corpo["receita_juros"]) == juros_auferidos

    def test_receita_anterior_ao_write_off_permanece_na_base(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Mesma prova do lado do write-off, e é a que sustenta a decisão da
        018 de CORTAR em vez de EXCLUIR a operação baixada.

        No Lucro Presumido não há dedução de perda que desfaça receita já
        auferida: o que venceu antes da baixa foi resultado de verdade e foi
        declarado. Excluir a operação inteira apagaria trimestres fechados.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # competência
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)

        vencida = _antecipar_vencimento(db_session, op_id, numero=1, dias=200)
        ano, trimestre = _trimestre_de(vencida)
        juros_auferidos = _juros_da_parcela(db_session, op_id, numero=1)
        assert juros_auferidos > 0

        db_session.execute(
            text("update operacao_credito set status = 'baixada_prejuizo' where id = :id"),
            {"id": str(op_id)},
        )
        db_session.commit()

        corpo = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        assert Decimal(corpo["receita_juros"]) == juros_auferidos

    def test_parcela_vencida_no_dia_do_corte_entra(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A borda do corte é INCLUSIVA, e ela não é exótica: renegociar ou
        baixar no dia do vencimento é rotina — é quando o tomador procura o
        credor.

        O juro corre até o vencimento; o ato praticado mais tarde no mesmo dia
        não desfaz competência já completada. Um `<` aqui declararia a MENOS no
        dia do corte, contra a mesma bússola que faz o coalesce cair em
        'infinity' quando o evento falta.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # competência
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)

        # Vence HOJE (data do banco), e o write-off é gravado agora: vencimento
        # e data do corte caem exatamente no mesmo dia.
        vencida = _antecipar_vencimento(db_session, op_id, numero=1, dias=0)
        ano, trimestre = _trimestre_de(vencida)
        juros_do_dia = _juros_da_parcela(db_session, op_id, numero=1)

        db_session.execute(
            text("update operacao_credito set status = 'baixada_prejuizo' where id = :id"),
            {"id": str(op_id)},
        )
        db_session.commit()

        corpo = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        # Só a parcela do dia do corte: as demais vencem depois dele e ficam de
        # fora — o mesmo número prova as duas metades da borda.
        assert Decimal(corpo["receita_juros"]) == juros_do_dia
        assert juros_do_dia > 0

    def test_operacao_liquidada_continua_na_base(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """CAMINHO FELIZ do filtro por status: quitar não pode apagar a receita.

        É o contraponto necessário aos dois testes acima — um filtro que
        excluísse estados terminais em bloco passaria neles e apagaria a
        receita de toda operação paga até o fim.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # competência
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)
        esperado = _juros_da_operacao_no_trimestre(db_session, op_id, ano, trimestre)

        quitar_operacao(db_session, op_id)
        db_session.execute(
            text("update operacao_credito set status = 'liquidada' where id = :id"),
            {"id": str(op_id)},
        )
        db_session.commit()

        corpo = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()
        assert Decimal(corpo["receita_juros"]) == esperado
        assert esperado > 0


# ---------------------------------------------------------------------
# (c) A âncora do regime de caixa — migration 018
# ---------------------------------------------------------------------


class TestAncoraDoRegimeDeCaixa:
    """`parcela.pago_em` é `clock_timestamp()` no instante da conciliação
    (009/016) — a data em que ALGUÉM MEXEU NO SISTEMA. A 011 ancorava nela,
    então um atraso rotineiro de conciliação deslocava receita entre
    trimestres, e a data de reconhecimento ficava ao alcance de quem opera.
    """

    def test_trimestre_e_o_do_credito_bancario(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        admin_client.post(
            "/api/fiscal/parametros", json={**PARAMETROS, "regime_reconhecimento": "caixa"}
        )
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        parcela = db_session.execute(
            text(
                "select id, valor_total, valor_juros from parcela "
                "where operacao_id = :o and numero = 1"
            ),
            {"o": str(op_id)},
        ).one()

        hoje = date.today()
        # Quatro meses é maior que a largura de um trimestre, então a data do
        # crédito cai sempre em outro trimestre que não o de hoje — o teste não
        # depende de em que mês do ano ele roda.
        credito = _meses_atras(hoje, 4)
        tri_credito = (credito.month - 1) // 3 + 1
        tri_hoje = (hoje.month - 1) // 3 + 1
        assert (credito.year, tri_credito) != (hoje.year, tri_hoje)

        movimento = registrar_movimento_bancario(
            db_session,
            data_movimento=credito,
            valor=parcela.valor_total,
            documento="FITID-ATRASO-CONCILIACAO",
        )
        # A conciliação acontece AGORA: pago_em fica no trimestre de hoje,
        # data_movimento no trimestre do crédito.
        baixar_parcela(db_session, parcela.id, movimento)

        no_credito = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": credito.year, "trimestre": tri_credito}
        ).json()
        no_sistema = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": hoje.year, "trimestre": tri_hoje}
        ).json()

        # O BLOQUEIO: a receita ficou no trimestre em que o dinheiro caiu...
        assert Decimal(no_credito["receita_juros"]) == parcela.valor_juros
        # ...e não no trimestre em que alguém abriu a tela para conciliar.
        assert Decimal(no_sistema["receita_juros"]) == Decimal("0.00")


# ---------------------------------------------------------------------
# (d) Mora e multa recebidas — migration 018
# ---------------------------------------------------------------------


class TestMoraEMulta:
    """fn_baixar_parcela aceita `valor >= valor_total` desde a 009 justamente
    porque o pagamento atrasado vem MAIOR que a parcela. A 011 somava só
    `parcela.valor_juros` e o excedente sumia — subdeclaração, o lado do erro
    que gera multa de ofício (Lei 9.430/96, art. 44, I).
    """

    def _baixar_com_excedente(
        self, db_session: Session, op_id: uuid.UUID, excedente: Decimal, data: date
    ) -> tuple[Decimal, Decimal]:
        """Baixa a parcela 1 com um crédito maior que ela. Devolve (juros, excedente)."""
        parcela = db_session.execute(
            text(
                "select id, valor_total, valor_juros from parcela "
                "where operacao_id = :o and numero = 1"
            ),
            {"o": str(op_id)},
        ).one()
        movimento = registrar_movimento_bancario(
            db_session,
            data_movimento=data,
            valor=parcela.valor_total + excedente,
            documento=f"FITID-MORA-{uuid.uuid4().hex[:8]}",
        )
        baixar_parcela(db_session, parcela.id, movimento)
        return parcela.valor_juros, excedente

    def test_excedente_do_credito_vira_receita_no_regime_caixa(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        admin_client.post(
            "/api/fiscal/parametros", json={**PARAMETROS, "regime_reconhecimento": "caixa"}
        )
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        hoje = date.today()
        juros, mora = self._baixar_com_excedente(db_session, op_id, Decimal("57.30"), hoje)

        c = admin_client.post(
            "/api/fiscal/apuracoes",
            json={"ano": hoje.year, "trimestre": (hoje.month - 1) // 3 + 1},
        ).json()

        # As duas naturezas ficam em linhas separadas: rendimento do contrato
        # de um lado, penalidade por atraso do outro.
        assert Decimal(c["receita_juros"]) == juros
        assert Decimal(c["receita_demais"]) == mora
        assert Decimal(c["receita_total"]) == juros + mora
        # E é o TOTAL que é tributado — não adiantaria registrar a mora numa
        # coluna que o cálculo ignora.
        assert Decimal(c["base_irpj"]) == round((juros + mora) * Decimal("0.32"), 2)
        assert Decimal(c["pis"]) == round((juros + mora) * Decimal("0.0065"), 2)

    def test_excedente_entra_tambem_no_regime_de_competencia(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Mora não existe na agenda: a 007 congela amortização, juros e total
        na ativação, e seu valor só é conhecido no instante do crédito
        bancário. Não há competência a que ancorá-la — o único fato observável
        é o extrato, nos dois regimes.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # competência
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        hoje = date.today()
        _, mora = self._baixar_com_excedente(db_session, op_id, Decimal("41.10"), hoje)

        c = admin_client.post(
            "/api/fiscal/apuracoes",
            json={"ano": hoje.year, "trimestre": (hoje.month - 1) // 3 + 1},
        ).json()
        assert Decimal(c["receita_demais"]) == mora

    def test_pagamento_exato_nao_inventa_receita(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """CAMINHO FELIZ: quem paga em dia não paga imposto sobre mora nenhuma.

        Sem este teste, um cálculo que somasse `movimento.valor` inteiro (em
        vez do excedente) passaria nos dois acima e dobraria a base de toda
        parcela paga pontualmente.
        """
        admin_client.post(
            "/api/fiscal/parametros", json={**PARAMETROS, "regime_reconhecimento": "caixa"}
        )
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        hoje = date.today()
        juros, _ = self._baixar_com_excedente(db_session, op_id, Decimal("0"), hoje)

        c = admin_client.post(
            "/api/fiscal/apuracoes",
            json={"ano": hoje.year, "trimestre": (hoje.month - 1) // 3 + 1},
        ).json()
        assert Decimal(c["receita_demais"]) == Decimal("0.00")
        assert Decimal(c["receita_total"]) == juros


# ---------------------------------------------------------------------
# Memória de cálculo — derivada do snapshot da própria apuração
# ---------------------------------------------------------------------


def _memoria(client_: TestClient, apuracao_id: str) -> dict:
    resposta = client_.get(f"/api/fiscal/apuracoes/{apuracao_id}/memoria")
    assert resposta.status_code == 200, resposta.text
    return resposta.json()  # type: ignore[no-any-return]


def _linha(memoria: dict, chave: str) -> dict:
    return next(linha for linha in memoria["linhas"] if linha["chave"] == chave)  # type: ignore[no-any-return]


class TestMemoriaDeCalculo:
    """A apuração é imutável (OC016) e chega ao contador como números prontos.

    Sem derivação, um número numa base que não pode ser corrigida é um número
    que ninguém consegue conferir nem contestar. A memória reproduz a
    aritmética de fn_apurar_trimestre a partir da PRÓPRIA linha gravada — as
    duas receitas e o snapshot de percentuais, alíquotas e limite —, e por isso
    ela pode DISCORDAR do valor gravado. Discordar é o ponto: se a fórmula
    mudar depois de uma apuração existir, é a única forma de o fato aparecer.
    """

    def test_memoria_confere_com_o_gravado(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O BLOQUEIO PRINCIPAL: a memória tem que reproduzir centavo a centavo
        o que o banco gravou, ou ela não serve para conferir nada.

        Inclui o arredondamento: o Postgres desempata para longe do zero e o
        Python, por default, para o par mais próximo. Uma memória escrita sem
        cuidar disso acusaria divergência de um centavo em apuração correta.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)
        apurada = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()

        memoria = _memoria(admin_client, apurada["id"])

        assert memoria["confere"] is True
        assert memoria["divergencias"] == []
        assert all(linha["confere"] for linha in memoria["linhas"])

        # Cada tributo recalculado bate com a coluna gravada...
        for chave in ("irpj", "adicional_irpj", "csll", "pis", "cofins"):
            linha = _linha(memoria, chave)
            assert Decimal(linha["valor"]) == Decimal(apurada[chave])
            assert Decimal(linha["valor_gravado"]) == Decimal(apurada[chave])
        # ...e o total também.
        assert Decimal(memoria["total_tributos"]) == Decimal(apurada["total_tributos"])
        assert Decimal(memoria["total_tributos_gravado"]) == Decimal(apurada["total_tributos"])

        # O cenário só prova algo se houve receita: com zero, qualquer fórmula
        # errada bateria com o gravado.
        assert Decimal(memoria["receita_total"]) > 0

    def test_derivacao_de_cada_tributo_e_explicita(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Receita considerada -> base (presunção, quando aplicável) ->
        alíquota -> valor. É o caminho que o contador vai refazer à mão.

        E a presunção é NULA em PIS/COFINS, não zero: cumulativos incidem sobre
        a receita, e presunção é conceito de IRPJ/CSLL. Zero ali seria uma
        presunção de 0%, que é outra afirmação — e daria base zero.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)
        apurada = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()

        memoria = _memoria(admin_client, apurada["id"])
        receita = Decimal(memoria["receita_total"])
        assert receita == Decimal(apurada["receita_juros"]) + Decimal(apurada["receita_demais"])

        irpj = _linha(memoria, "irpj")
        assert Decimal(irpj["receita_considerada"]) == receita
        assert Decimal(irpj["percentual_presuncao"]) == Decimal("0.32")
        assert Decimal(irpj["base_calculo"]) == round(receita * Decimal("0.32"), 2)
        assert Decimal(irpj["aliquota"]) == Decimal("0.15")
        assert Decimal(irpj["valor"]) == round(Decimal(irpj["base_calculo"]) * Decimal("0.15"), 2)

        csll = _linha(memoria, "csll")
        assert Decimal(csll["base_calculo"]) == round(receita * Decimal("0.32"), 2)
        assert Decimal(csll["valor"]) == round(Decimal(csll["base_calculo"]) * Decimal("0.09"), 2)

        for chave, aliquota in (("pis", Decimal("0.0065")), ("cofins", Decimal("0.03"))):
            linha = _linha(memoria, chave)
            assert linha["percentual_presuncao"] is None
            assert Decimal(linha["base_calculo"]) == receita
            assert Decimal(linha["valor"]) == round(receita * aliquota, 2)

    def test_adicional_mostra_limite_e_excedente_zerado_abaixo_do_limite(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Sem limite e excedente à vista, "adicional 0,00" parece esquecimento
        em vez de "a base não chegou ao limite do trimestre" — e é a linha que
        mais gera dúvida.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)  # limite 60.000
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)
        apurada = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()

        adicional = _linha(_memoria(admin_client, apurada["id"]), "adicional_irpj")
        assert Decimal(adicional["limite"]) == Decimal("60000.00")
        assert Decimal(adicional["base_calculo"]) < Decimal("60000.00")
        assert Decimal(adicional["excedente"]) == Decimal("0")
        assert Decimal(adicional["valor"]) == Decimal("0.00")
        assert adicional["confere"] is True

    def test_adicional_aparece_acima_do_limite(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O OUTRO LADO. Sem este teste, uma memória que devolvesse excedente
        sempre zero passaria no anterior.

        O limite baixo é artifício de cenário — o valor real é matéria
        tributária e vem do parâmetro, como tudo mais.
        """
        admin_client.post(
            "/api/fiscal/parametros", json={**PARAMETROS, "adicional_irpj_limite": "10.00"}
        )
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        ano, trimestre = _trimestre_da_parcela(db_session, op_id, 1)
        apurada = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": ano, "trimestre": trimestre}
        ).json()

        adicional = _linha(_memoria(admin_client, apurada["id"]), "adicional_irpj")
        base = Decimal(adicional["base_calculo"])
        assert base > Decimal("10.00")
        # O excedente é a base MENOS o limite, e o adicional incide só sobre
        # ele — nunca sobre a base inteira.
        assert Decimal(adicional["excedente"]) == base - Decimal("10.00")
        assert Decimal(adicional["valor"]) == round((base - Decimal("10.00")) * Decimal("0.10"), 2)
        assert Decimal(adicional["valor"]) > 0
        assert Decimal(adicional["valor"]) == Decimal(apurada["adicional_irpj"])

    def test_memoria_usa_o_snapshot_e_nao_o_parametro_de_hoje(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """A memória se deriva da linha imutável, não do parâmetro vigente.

        Se ela lesse `parametro_fiscal`, a memória de um trimestre antigo
        mudaria sozinha na primeira alteração de alíquota — que é exatamente o
        defeito que o snapshot da 011 existe para impedir.
        """
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        apurada = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1}
        ).json()

        admin_client.post(
            "/api/fiscal/parametros",
            json={**PARAMETROS, "vigencia_inicio": "2024-01-01", "aliquota_irpj": "0.25"},
        )

        memoria = _memoria(admin_client, apurada["id"])
        assert Decimal(_linha(memoria, "irpj")["aliquota"]) == Decimal("0.15")
        assert memoria["confere"] is True

    def test_divergencia_e_denunciada_quando_a_formula_discorda_do_gravado(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """O CASO QUE JUSTIFICA A MEMÓRIA EXISTIR.

        Um valor gravado que a fórmula atual não reproduz só acontece se a
        fórmula mudou depois da apuração — foi o que a 018 fez com a 011. OC016
        impede corrigir a linha, então esconder a divergência deixaria uma
        declaração errada com aparência de auditada; a única providência
        possível é retificar o trimestre, e para isso é preciso vê-la.

        O cenário é montado por INSERT direto, e não por UPDATE: o trigger da
        011 é `before update or delete`, então inserir uma linha já torta não
        precisa desligar proteção nenhuma — e é assim que uma apuração gravada
        por uma fórmula antiga de fato existiria no banco.
        """
        torto = db_session.execute(
            text("""
            insert into apuracao_fiscal (
                ano, trimestre, versao, receita_juros, receita_demais,
                base_irpj, irpj, adicional_irpj, base_csll, csll, pis, cofins, total_tributos,
                percentual_presuncao_irpj, percentual_presuncao_csll,
                aliquota_irpj, aliquota_csll, adicional_irpj_aliquota, adicional_irpj_limite,
                aliquota_pis, aliquota_cofins, regime_reconhecimento
            ) values (
                2021, 3, 1, 1000.00, 0.00,
                320.00, 999.99, 0.00, 320.00, 28.80, 6.50, 30.00, 1065.29,
                0.32, 0.32, 0.15, 0.09, 0.10, 60000.00, 0.0065, 0.03, 'competencia'
            ) returning id
            """)
        ).scalar_one()
        db_session.commit()

        memoria = _memoria(admin_client, str(torto))

        assert memoria["confere"] is False
        divergentes = {d["campo"]: d for d in memoria["divergencias"]}
        # O IRPJ gravado (999,99) não é o que 320,00 x 15% produz (48,00)...
        assert Decimal(divergentes["irpj"]["calculado"]) == Decimal("48.00")
        assert Decimal(divergentes["irpj"]["gravado"]) == Decimal("999.99")
        assert Decimal(divergentes["irpj"]["diferenca"]) == Decimal("-951.99")
        # ...e o total carrega o erro junto, sem ninguém precisar somar à mão.
        assert Decimal(divergentes["total_tributos"]["calculado"]) == Decimal("113.30")
        assert Decimal(divergentes["total_tributos"]["gravado"]) == Decimal("1065.29")

        # A linha do tributo divergente é marcada, para a tela não precisar
        # cruzar a lista de divergências com a tabela.
        assert _linha(memoria, "irpj")["confere"] is False
        # E o que está certo continua certo: uma memória que marcasse tudo como
        # divergente ao primeiro erro seria tão inútil quanto uma que não
        # marcasse nada.
        assert _linha(memoria, "csll")["confere"] is True
        assert "csll" not in divergentes

    def test_memoria_da_versao_retificada_continua_acessivel(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """Busca por id, não por (ano, trimestre): a versão 1 permanece no
        banco e a memória dela é o que explica a diferença entre o que foi
        declarado e o que foi retificado."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        primeira = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1}
        ).json()
        segunda = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1}
        ).json()

        assert _memoria(admin_client, primeira["id"])["versao"] == 1
        assert _memoria(admin_client, segunda["id"])["versao"] == 2

    def test_operador_confere_a_memoria(
        self, admin_client: TestClient, operador_client: TestClient
    ) -> None:
        """Quem apura é o admin; quem confere é o contador. Conferência que
        exige privilégio de escrita não é conferência."""
        admin_client.post("/api/fiscal/parametros", json=PARAMETROS)
        apurada = admin_client.post(
            "/api/fiscal/apuracoes", json={"ano": 2021, "trimestre": 1}
        ).json()

        # O override de admin SAI DE CENA aqui. As duas fixtures compartilham o
        # mesmo TestClient, e deixá-lo de pé faz `Depends(get_admin_user)`
        # devolver o admin até na requisição do operador — o teste passaria
        # verde com a rota fechada ao contador, afirmando o contrário do que
        # verifica. Sem o override, quem responde é a dependência de verdade.
        app.dependency_overrides.pop(get_admin_user, None)

        resposta = operador_client.get(f"/api/fiscal/apuracoes/{apurada['id']}/memoria")
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["confere"] is True

    def test_memoria_inclui_a_mora_na_base(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A base é a receita TOTAL: juro contratual MAIS mora recebida (018).

        Em todos os outros cenários desta classe a mora é zero, então uma
        memória que derivasse tudo de `receita_juros` passaria em todos eles —
        e acusaria divergência em toda apuração de carteira que recebe
        atrasado, que numa ESC de microcrédito é a maioria. Alarme falso no
        indicador que existe justamente para ser confiável é pior que
        indicador nenhum.
        """
        admin_client.post(
            "/api/fiscal/parametros", json={**PARAMETROS, "regime_reconhecimento": "caixa"}
        )
        op_id = _operacao_com_agenda(db_session, tomador_autorizado)
        hoje = date.today()
        parcela = db_session.execute(
            text(
                "select id, valor_total, valor_juros from parcela "
                "where operacao_id = :o and numero = 1"
            ),
            {"o": str(op_id)},
        ).one()
        mora = Decimal("57.30")
        movimento = registrar_movimento_bancario(
            db_session,
            data_movimento=hoje,
            valor=parcela.valor_total + mora,
            documento=f"FITID-MEMORIA-{uuid.uuid4().hex[:8]}",
        )
        baixar_parcela(db_session, parcela.id, movimento)

        apurada = admin_client.post(
            "/api/fiscal/apuracoes",
            json={"ano": hoje.year, "trimestre": (hoje.month - 1) // 3 + 1},
        ).json()
        memoria = _memoria(admin_client, apurada["id"])

        receita = parcela.valor_juros + mora
        # O cenário só prova algo se a mora existir de verdade.
        assert Decimal(memoria["receita_demais"]) == mora
        assert Decimal(memoria["receita_total"]) == receita
        # A receita considerada de CADA tributo é a total, não só o juro.
        for chave in ("irpj", "adicional_irpj", "csll", "pis", "cofins"):
            assert Decimal(_linha(memoria, chave)["receita_considerada"]) == receita
        assert Decimal(_linha(memoria, "irpj")["base_calculo"]) == round(
            receita * Decimal("0.32"), 2
        )
        assert Decimal(_linha(memoria, "pis")["base_calculo"]) == receita
        assert memoria["confere"] is True

    def test_arredondamento_empatado_nao_vira_divergencia(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """O EMPATE, que é onde as duas linguagens discordam.

        O Postgres desempata para LONGE DO ZERO; o `round` do Python vai para o
        par mais próximo. Numa apuração cujo produto cai exatamente na metade,
        as duas regras diferem em um centavo — e a memória denunciaria como
        erro uma conta que está certa, com a providência escrita na tela sendo
        retificar um trimestre que não tem defeito nenhum.

        Receita 9,69 com presunção de 32% dá base 3,10; 3,10 x 15% = 0,465,
        empate exato. O banco grava 0,47; o Python "correto por default" diria
        0,46. As colunas são calculadas AQUI pelas mesmas expressões da 018,
        para o esperado vir do Postgres e não da aritmética do teste.

        INSERT direto, e não `fn_apurar_trimestre`: a receita precisa ser um
        valor escolhido a dedo para cair no empate, e ela é derivada da agenda.
        O trigger OC016 é `before update or delete`, então inserir não desliga
        proteção nenhuma.
        """
        empatada = db_session.execute(
            text("""
            with p as (
                select 9.69::numeric(14,2)     as receita,
                       0.3200::numeric(6,4)    as presuncao,
                       0.1500::numeric(6,4)    as ali_irpj,
                       0.0900::numeric(6,4)    as ali_csll,
                       0.1000::numeric(6,4)    as ad_ali,
                       60000.00::numeric(14,2) as ad_limite,
                       0.0065::numeric(6,4)    as ali_pis,
                       0.0300::numeric(6,4)    as ali_cofins
            ), b as (
                select p.*, round(receita * presuncao, 2) as base from p
            ), t as (
                select b.*,
                       round(base * ali_irpj, 2) as irpj,
                       round(greatest(base - ad_limite, 0) * ad_ali, 2) as adicional,
                       round(base * ali_csll, 2) as csll,
                       round(receita * ali_pis, 2) as pis,
                       round(receita * ali_cofins, 2) as cofins
                from b
            )
            insert into apuracao_fiscal (
                ano, trimestre, versao, receita_juros, receita_demais,
                base_irpj, irpj, adicional_irpj, base_csll, csll, pis, cofins, total_tributos,
                percentual_presuncao_irpj, percentual_presuncao_csll,
                aliquota_irpj, aliquota_csll, adicional_irpj_aliquota, adicional_irpj_limite,
                aliquota_pis, aliquota_cofins, regime_reconhecimento
            )
            select 2022, 2, 1, receita, 0,
                   base, irpj, adicional, base, csll, pis, cofins,
                   irpj + adicional + csll + pis + cofins,
                   presuncao, presuncao, ali_irpj, ali_csll, ad_ali, ad_limite,
                   ali_pis, ali_cofins, 'competencia'
            from t
            returning id
            """)
        ).scalar_one()
        db_session.commit()

        memoria = _memoria(admin_client, str(empatada))

        # O empate aconteceu mesmo: o banco arredondou 0,465 para longe do zero.
        assert Decimal(_linha(memoria, "irpj")["valor_gravado"]) == Decimal("0.47")
        # E a memória chegou ao MESMO centavo — com o default do Python daria
        # 0,46 e esta apuração correta apareceria como divergente.
        assert Decimal(_linha(memoria, "irpj")["valor"]) == Decimal("0.47")
        assert memoria["confere"] is True
        assert memoria["divergencias"] == []

    def test_apuracao_inexistente_e_404(self, admin_client: TestClient) -> None:
        resposta = admin_client.get(f"/api/fiscal/apuracoes/{uuid.uuid4()}/memoria")
        assert resposta.status_code == 404
