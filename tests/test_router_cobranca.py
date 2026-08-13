"""
Testes do router HTTP /cobranca — painel de aging e execução da régua.

O ponto sensível é a autorização: declarar inadimplência em lote não é
operação de rotina, e o teste prova que operador não consegue disparar.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.security import get_admin_user, get_current_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.conftest import confirmar_registro


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
        id=uuid.uuid4(), email="admin@orgatec.com", nome="Admin Teste", papel="admin", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_admin_user] = lambda: admin
    return client


@pytest.fixture()
def operador_client(client: TestClient) -> TestClient:
    """Só sobrescreve get_current_user — a checagem de papel em
    get_admin_user roda de verdade."""
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    return client


def _operacao_atrasada(db_session: Session, tomador_id: uuid.UUID, dias: int) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 2.5, 'PRICE', 12, 'registrada', 'REG-COB')
        returning id
        """),
        {"t": str(tomador_id)},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)

    # Vencimento é imutável (OC009); o trigger é desabilitado só para
    # fabricar o cenário — pela API isso é impossível, por construção.
    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    # Ancorado em `current_date` do BANCO — ver a explicação em
    # tests/test_aging.py::_envelhecer. Usar date.today() do Python quebrava
    # este teste todo dia na janela em que os dois relógios discordam.
    db_session.execute(
        text(
            "update parcela set vencimento = current_date - cast(:dias as int) "
            "where operacao_id = :id and numero = 1"
        ),
        {"dias": dias, "id": str(op_id)},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()
    return op_id


class TestGetAging:
    def test_exige_autenticacao(self, client: TestClient) -> None:
        assert client.get("/api/cobranca/aging").status_code == 401

    def test_sem_operacoes_traz_todas_as_faixas_zeradas(self, admin_client: TestClient) -> None:
        """Faixa vazia aparece com zero em vez de sumir: um painel que omite
        'acima de 90' não distingue 'não há nada' de 'não carregou'."""
        response = admin_client.get("/api/cobranca/aging")

        assert response.status_code == 200
        body = response.json()
        assert body["operacoes"] == []
        assert [f["faixa"] for f in body["resumo"]] == [
            "em_dia",
            "ate_30",
            "de_31_a_60",
            "de_61_a_90",
            "acima_de_90",
        ]
        assert all(f["quantidade"] == 0 for f in body["resumo"])

    def test_classifica_e_soma_por_faixa(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        _operacao_atrasada(db_session, tomador_autorizado, dias=100)
        _operacao_atrasada(db_session, tomador_autorizado, dias=45)

        body = admin_client.get("/api/cobranca/aging").json()

        assert len(body["operacoes"]) == 2
        # Mais atrasada primeiro — a ordem é a prioridade de cobrança.
        assert body["operacoes"][0]["dias_atraso"] == 100
        assert body["operacoes"][0]["faixa"] == "acima_de_90"
        assert body["operacoes"][1]["faixa"] == "de_31_a_60"

        por_faixa = {f["faixa"]: f for f in body["resumo"]}
        assert por_faixa["acima_de_90"]["quantidade"] == 1
        assert por_faixa["de_31_a_60"]["quantidade"] == 1
        assert Decimal(por_faixa["acima_de_90"]["valor_vencido"]) > 0


class TestProcessarAging:
    def test_operador_nao_pode_disparar_a_regua(self, operador_client: TestClient) -> None:
        """Declarar inadimplência em lote tem consequência para os tomadores
        — é ato de admin."""
        response = operador_client.post("/api/cobranca/aging/processar", json={})
        assert response.status_code == 403

    def test_transiciona_e_e_idempotente(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=100)

        primeira = admin_client.post("/api/cobranca/aging/processar", json={})
        assert primeira.status_code == 200
        assert primeira.json() == {"transicionadas": 1, "limite_dias": 90}

        segunda = admin_client.post("/api/cobranca/aging/processar", json={})
        assert segunda.json()["transicionadas"] == 0

        status = db_session.execute(
            text("select status from operacao_credito where id = :id"), {"id": str(op_id)}
        ).scalar_one()
        assert status == "inadimplente"

    def test_limite_customizado(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O prazo é parâmetro de negócio: a ESC pode adotar outro sem
        alterar a lógica."""
        _operacao_atrasada(db_session, tomador_autorizado, dias=45)

        assert (
            admin_client.post("/api/cobranca/aging/processar", json={}).json()["transicionadas"]
            == 0
        )
        assert (
            admin_client.post("/api/cobranca/aging/processar", json={"limite_dias": 30}).json()[
                "transicionadas"
            ]
            == 1
        )

    def test_limite_invalido_e_recusado(self, admin_client: TestClient) -> None:
        assert (
            admin_client.post("/api/cobranca/aging/processar", json={"limite_dias": 0}).status_code
            == 422
        )


class TestMovimentosEBaixa:
    def test_registrar_movimento_e_listar(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": "1500.00",
                "documento": "FITID-ROUTER-1",
                "descricao": "TED recebida",
            },
        )
        assert response.status_code == 201
        assert response.json()["conciliado"] is False

        lista = admin_client.get("/api/cobranca/movimentos").json()
        assert [m["documento"] for m in lista] == ["FITID-ROUTER-1"]

    def test_documento_duplicado_vira_422(self, admin_client: TestClient) -> None:
        """Reimportar o mesmo extrato é rotina; a resposta precisa dizer o
        que houve, não vazar o nome da constraint."""
        corpo = {
            "data_movimento": str(date.today()),
            "valor": "1500.00",
            "documento": "FITID-DUP",
        }
        assert admin_client.post("/api/cobranca/movimentos", json=corpo).status_code == 201

        repetido = admin_client.post("/api/cobranca/movimentos", json=corpo)
        assert repetido.status_code == 422
        assert "Já existe um movimento" in repetido.json()["detail"]

    def test_baixa_pelo_endpoint(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=10)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
            {"op": str(op_id)},
        ).one()

        movimento_id = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": str(parcela.valor_total),
                "documento": "FITID-BAIXA",
            },
        ).json()["id"]

        baixa = admin_client.post(
            f"/api/cobranca/parcelas/{parcela.id}/baixar", json={"movimento_id": movimento_id}
        )
        assert baixa.status_code == 204

        # O movimento sai da lista de disponíveis: o diálogo de baixa não
        # pode oferecer algo que o banco recusaria.
        disponiveis = admin_client.get(
            "/api/cobranca/movimentos", params={"apenas_disponiveis": True}
        ).json()
        assert disponiveis == []

    def test_baixa_sem_lastro_suficiente_vira_422(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=10)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
            {"op": str(op_id)},
        ).one()

        movimento_id = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": "1.00",
                "documento": "FITID-CURTO",
            },
        ).json()["id"]

        resposta = admin_client.post(
            f"/api/cobranca/parcelas/{parcela.id}/baixar", json={"movimento_id": movimento_id}
        )
        assert resposta.status_code == 422
        assert resposta.json()["codigo"] == "OC011"
