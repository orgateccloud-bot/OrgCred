"""
Apuração fiscal no Lucro Presumido (migration 011) contra Postgres real.

Duas coisas que este arquivo existe para travar:

1. Que a base seja SÓ O JURO. Somar amortização — devolução de principal —
   inflaria a tributação em várias vezes sobre dinheiro que não é resultado.
2. Que sem parâmetro configurado a apuração RECUSE, em vez de devolver um
   número plausível calculado com alíquota inventada pelo sistema.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, baixar_parcela, registrar_movimento_bancario
from app.core.security import get_admin_user, get_current_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.conftest import sqlstate_de


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
    ativar_operacao(db_session, op_id)
    return op_id


def _trimestre_da_parcela(db_session: Session, op_id: uuid.UUID, numero: int) -> tuple[int, int]:
    venc = db_session.execute(
        text("select vencimento from parcela where operacao_id = :o and numero = :n"),
        {"o": str(op_id), "n": numero},
    ).scalar_one()
    return venc.year, (venc.month - 1) // 3 + 1


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

    def test_regime_caixa_usa_a_data_da_baixa(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """No caixa, só o que foi efetivamente recebido entra — e o que
        entra é o que tem lastro bancário (migration 009)."""
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
