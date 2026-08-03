"""
Testes HTTP da renegociação atômica (/api/cobranca) e das transições da
régua expostas em /api/operacoes (marcar-inadimplente, liquidar) — auth,
papel e tradução dos erros de negócio para o envelope unificado
{"detail": ..., "codigo": ...}.
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_operador_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.test_capital_engine import _criar_e_ativar_operacao_direto, _criar_operacao


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient com get_db() sobrescrito para a sessão de teste transacional."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def authed_client(client: TestClient) -> TestClient:
    """Client autenticado com papel operador."""
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    app.dependency_overrides[get_operador_user] = lambda: operador
    return client


def _renegociacao_payload(valor: int = 35_000) -> dict:
    return {
        "valor_principal": valor,
        "taxa_juros_mensal": 3.0,
        "numero_parcelas": 24,
        "sistema_amortizacao": "PRICE",
        "registro_entidade_ref": "REG-NOVACAO-HTTP",
    }


class TestAutenticacao:
    def test_renegociacao_sem_token_401(self, client: TestClient) -> None:
        response = client.post(
            f"/api/cobranca/operacoes/{uuid.uuid4()}/renegociacao",
            json=_renegociacao_payload(),
        )
        assert response.status_code == 401
        assert response.json()["codigo"] == "TOKEN_AUSENTE"

    def test_marcar_inadimplente_sem_token_401(self, client: TestClient) -> None:
        response = client.post(f"/api/operacoes/{uuid.uuid4()}/marcar-inadimplente")
        assert response.status_code == 401


class TestReguaDeCobranca:
    """Transições da régua via /api/operacoes — inadimplente segue
    comprometendo o teto (migration 006), cura via /ativar."""

    def test_marcar_inadimplente_e_regularizar(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")

        r1 = authed_client.post(f"/api/operacoes/{op_id}/marcar-inadimplente")
        assert r1.status_code == 200
        assert r1.json()["status"] == "inadimplente"

        # inadimplente segue comprometendo o teto (G1 fechado)
        capital = authed_client.get("/api/capital/disponivel")
        assert float(capital.json()["disponivel"]) == 20_000.0

        # cura do atraso: inadimplente -> ativa via /ativar
        r2 = authed_client.post(f"/api/operacoes/{op_id}/ativar")
        assert r2.status_code == 200
        assert r2.json()["status"] == "ativa"

    def test_marcar_inadimplente_de_registrada_409_oc003(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000)

        response = authed_client.post(f"/api/operacoes/{op_id}/marcar-inadimplente")

        assert response.status_code == 409
        assert response.json()["codigo"] == "OC003"

    def test_liquidar_libera_capital(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-A")

        response = authed_client.post(f"/api/operacoes/{op_id}/liquidar")

        assert response.status_code == 200
        assert response.json()["status"] == "liquidada"

        capital = authed_client.get("/api/capital/disponivel")
        assert float(capital.json()["disponivel"]) == 50_000.0


class TestRenegociacaoAtomica:
    def test_renegociacao_ok(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-OLD")

        response = authed_client.post(
            f"/api/cobranca/operacoes/{op_id}/renegociacao", json=_renegociacao_payload(35_000)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["antiga"]["id"] == str(op_id)
        assert body["antiga"]["status"] == "renegociada"
        assert body["nova"]["status"] == "ativa"
        assert body["nova"]["registro_entidade_ref"] == "REG-NOVACAO-HTTP"

    def test_renegociacao_acima_do_teto_422_oc001(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _criar_e_ativar_operacao_direto(db_session, tomador_autorizado, 30_000, "REG-OLD")

        response = authed_client.post(
            f"/api/cobranca/operacoes/{op_id}/renegociacao", json=_renegociacao_payload(60_000)
        )

        assert response.status_code == 422
        assert response.json()["codigo"] == "OC001"

    def test_renegociacao_de_proposta_409_oc003(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 10_000, status="proposta")

        response = authed_client.post(
            f"/api/cobranca/operacoes/{op_id}/renegociacao", json=_renegociacao_payload(10_000)
        )

        assert response.status_code == 409
        assert response.json()["codigo"] == "OC003"

    def test_renegociacao_inexistente_404(self, authed_client: TestClient) -> None:
        response = authed_client.post(
            f"/api/cobranca/operacoes/{uuid.uuid4()}/renegociacao",
            json=_renegociacao_payload(),
        )
        assert response.status_code == 404
        assert response.json()["codigo"] == "OPERACAO_NAO_ENCONTRADA"

    def test_renegociacao_payload_invalido_422_pydantic(self, authed_client: TestClient) -> None:
        payload = _renegociacao_payload()
        payload["valor_principal"] = 0  # gt=0

        response = authed_client.post(
            f"/api/cobranca/operacoes/{uuid.uuid4()}/renegociacao", json=payload
        )

        assert response.status_code == 422
