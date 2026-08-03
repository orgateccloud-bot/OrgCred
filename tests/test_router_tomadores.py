"""
Testes do router HTTP /api/tomadores — cadastro: validação de dígito
verificador do CNPJ (TM001), duplicidade (TM003), contrato de entrada
(pydantic: formato do CNPJ, porte, UF), gate geográfico restrito a admin
e enforcement de autenticação/autorização.
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.main import app
from app.models import Usuario


# CNPJs com dígito verificador válido usados nos testes.
CNPJ_VALIDO = "11222333000181"
CNPJ_VALIDO_2 = "04252011000110"


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient com get_db() sobrescrito para a sessão de teste transacional."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _operador() -> Usuario:
    return Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador", papel="operador", ativo=True
    )


def _admin() -> Usuario:
    return Usuario(
        id=uuid.uuid4(), email="admin@orgatec.com", nome="Admin", papel="admin", ativo=True
    )


@pytest.fixture()
def operador_client(client: TestClient) -> TestClient:
    """Autenticado como operador (get_admin_user roda de verdade)."""
    op = _operador()
    app.dependency_overrides[get_current_user] = lambda: op
    app.dependency_overrides[get_operador_user] = lambda: op
    return client


@pytest.fixture()
def admin_client(client: TestClient) -> TestClient:
    """Autenticado como admin."""
    adm = _admin()
    app.dependency_overrides[get_current_user] = lambda: adm
    app.dependency_overrides[get_operador_user] = lambda: adm
    app.dependency_overrides[get_admin_user] = lambda: adm
    return client


def _payload(**over: object) -> dict:
    base = {
        "cnpj": CNPJ_VALIDO,
        "razao_social": "Padaria do Zé ME",
        "porte": "ME",
        "municipio": "Formoso",
        "uf": "GO",
    }
    base.update(over)
    return base


class TestCadastroSemAutenticacao:
    def test_post_sem_token_retorna_401(self, client: TestClient) -> None:
        response = client.post("/api/tomadores", json=_payload())
        assert response.status_code == 401
        assert response.json()["codigo"] == "TOKEN_AUSENTE"


class TestCadastroComPermissao:
    def test_cadastro_valido_retorna_201_nao_autorizado_por_padrao(
        self, operador_client: TestClient
    ) -> None:
        response = operador_client.post("/api/tomadores", json=_payload())
        assert response.status_code == 201
        body = response.json()
        assert body["cnpj"] == CNPJ_VALIDO
        assert body["porte"] == "ME"
        # Regra: nasce sempre sem autorização geográfica.
        assert body["municipio_autorizado"] is False

    def test_porte_mei_aceito(self, operador_client: TestClient) -> None:
        """LC 167/2019 cobre MEI além de ME/EPP."""
        response = operador_client.post(
            "/api/tomadores", json=_payload(cnpj=CNPJ_VALIDO_2, porte="MEI")
        )
        assert response.status_code == 201
        assert response.json()["porte"] == "MEI"

    def test_cnpj_com_mascara_rejeitado_pelo_contrato(self, operador_client: TestClient) -> None:
        """Contrato de entrada é somente dígitos (pattern pydantic)."""
        response = operador_client.post("/api/tomadores", json=_payload(cnpj="11.222.333/0001-81"))
        assert response.status_code == 422

    def test_cnpj_dv_invalido_retorna_422_tm001(self, operador_client: TestClient) -> None:
        # Formato ok (14 dígitos), dígito verificador não confere
        response = operador_client.post("/api/tomadores", json=_payload(cnpj="11222333000199"))
        assert response.status_code == 422
        assert response.json()["codigo"] == "TM001"

    def test_porte_invalido_rejeitado_pelo_contrato(self, operador_client: TestClient) -> None:
        response = operador_client.post("/api/tomadores", json=_payload(porte="GRANDE"))
        assert response.status_code == 422

    def test_cnpj_duplicado_retorna_409_tm003(self, operador_client: TestClient) -> None:
        primeiro = operador_client.post("/api/tomadores", json=_payload())
        assert primeiro.status_code == 201
        segundo = operador_client.post("/api/tomadores", json=_payload(razao_social="Outra ME"))
        assert segundo.status_code == 409
        assert segundo.json()["codigo"] == "TM003"


class TestLeitura:
    def test_listar_inclui_cadastrado(self, operador_client: TestClient) -> None:
        operador_client.post("/api/tomadores", json=_payload())
        response = operador_client.get("/api/tomadores")
        assert response.status_code == 200
        cnpjs = [t["cnpj"] for t in response.json()]
        assert CNPJ_VALIDO in cnpjs

    def test_obter_por_id_inclui_operacoes(self, operador_client: TestClient) -> None:
        criado = operador_client.post("/api/tomadores", json=_payload()).json()
        response = operador_client.get(f"/api/tomadores/{criado['id']}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == criado["id"]
        assert body["operacoes"] == []

    def test_obter_inexistente_retorna_404(self, operador_client: TestClient) -> None:
        response = operador_client.get(f"/api/tomadores/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["codigo"] == "TOMADOR_NAO_ENCONTRADO"


class TestGateGeografico:
    def test_operador_nao_pode_autorizar_municipio_403(self, operador_client: TestClient) -> None:
        criado = operador_client.post("/api/tomadores", json=_payload()).json()
        response = operador_client.patch(
            f"/api/tomadores/{criado['id']}/autorizacao", json={"municipio_autorizado": True}
        )
        assert response.status_code == 403
        assert response.json()["codigo"] == "PERMISSAO_NEGADA"

    def test_admin_autoriza_municipio_200(self, admin_client: TestClient) -> None:
        criado = admin_client.post("/api/tomadores", json=_payload()).json()
        assert criado["municipio_autorizado"] is False
        response = admin_client.patch(
            f"/api/tomadores/{criado['id']}/autorizacao", json={"municipio_autorizado": True}
        )
        assert response.status_code == 200
        assert response.json()["municipio_autorizado"] is True

    def test_admin_revoga_municipio(self, admin_client: TestClient) -> None:
        criado = admin_client.post("/api/tomadores", json=_payload(cnpj=CNPJ_VALIDO_2)).json()
        admin_client.patch(
            f"/api/tomadores/{criado['id']}/autorizacao", json={"municipio_autorizado": True}
        )
        response = admin_client.patch(
            f"/api/tomadores/{criado['id']}/autorizacao", json={"municipio_autorizado": False}
        )
        assert response.status_code == 200
        assert response.json()["municipio_autorizado"] is False

    def test_autorizar_inexistente_retorna_404(self, admin_client: TestClient) -> None:
        response = admin_client.patch(
            f"/api/tomadores/{uuid.uuid4()}/autorizacao", json={"municipio_autorizado": True}
        )
        assert response.status_code == 404
