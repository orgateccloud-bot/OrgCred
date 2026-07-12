"""
Testes do router HTTP /operacoes — valida tradução de exceção de domínio
para status HTTP (404/409/422) e enforcement de autenticação/autorização.
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_operador
from app.core.security import CurrentUser
from app.db import get_db
from app.main import app


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient com get_db() sobrescrito para usar a sessão de teste transacional."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def authed_client(client: TestClient) -> TestClient:
    """Client com autenticação mockada (papel operador)."""
    operador = CurrentUser(user_id="test-user", email="op@orgatec.com", papel="operador")
    app.dependency_overrides[get_current_user] = lambda: operador
    app.dependency_overrides[require_operador] = lambda: operador
    return client


class TestAtivarOperacaoSemAutenticacao:
    def test_sem_authorization_header_retorna_401(
        self, client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        response = client.post(f"/operacoes/{uuid.uuid4()}/ativar")
        assert response.status_code == 401
        assert response.json()["codigo"] == "TOKEN_AUSENTE"


class TestAtivarOperacaoComPermissao:
    def test_operacao_inexistente_retorna_404(self, authed_client: TestClient) -> None:
        response = authed_client.post(f"/operacoes/{uuid.uuid4()}/ativar")
        assert response.status_code == 404

    def test_operacao_dentro_do_teto_retorna_200(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        result = db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
                values
                    (:tomador_id, 'emprestimo', 30000, 2.5, 'PRICE', 12, 'registrada', 'REG-HTTP')
                returning id
                """
            ),
            {"tomador_id": str(tomador_autorizado)},
        )
        db_session.commit()
        op_id = result.scalar_one()

        response = authed_client.post(f"/operacoes/{op_id}/ativar")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ativa"
        assert body["id"] == str(op_id)

    def test_operacao_acima_do_teto_retorna_422_com_codigo(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        # Comprometer 30k de capital: insere como 'registrada' e ativa via UPDATE
        # (a máquina de estados do trigger só permite INSERT em proposta/registrada)
        db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
                values
                    (:tomador_id, 'emprestimo', 30000, 2.5, 'PRICE', 12, 'registrada', 'REG-A')
                """
            ),
            {"tomador_id": str(tomador_autorizado)},
        )
        db_session.execute(
            text(
                "update operacao_credito set status = 'ativa' where registro_entidade_ref = 'REG-A'"
            )
        )
        result = db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
                values
                    (:tomador_id, 'emprestimo', 25000, 2.5, 'PRICE', 12, 'registrada', 'REG-B')
                returning id
                """
            ),
            {"tomador_id": str(tomador_autorizado)},
        )
        db_session.commit()
        op_id = result.scalar_one()

        response = authed_client.post(f"/operacoes/{op_id}/ativar")

        assert response.status_code == 422
        body = response.json()
        # HTTPException(detail=<dict>) aninha o payload sob "detail"
        assert body["detail"]["codigo"] == "OC001"
