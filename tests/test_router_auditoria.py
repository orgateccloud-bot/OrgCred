"""Testes do router HTTP /auditoria — trilha de auditoria (hash-chain)."""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.security import get_current_user
from app.db import get_db
from app.main import app
from app.models import Usuario


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def authed_client(client: TestClient) -> TestClient:
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador Teste", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    return client


class TestAuditoria:
    def test_sem_autenticacao_retorna_401(self, client: TestClient) -> None:
        response = client.get("/api/auditoria")
        assert response.status_code == 401

    def test_sem_eventos_cadeia_integra_e_vazia(self, authed_client: TestClient) -> None:
        response = authed_client.get("/api/auditoria")
        assert response.status_code == 200
        body = response.json()
        assert body["integro"] is True
        assert body["quebras"] == []
        assert body["eventos"] == []

    def test_apos_ativacao_evento_aparece_com_autor_e_hash(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        db_session.execute(
            text(
                "insert into usuario (id, email, nome, papel) values (:id, 'a@b.com', 'Ana', 'operador')"
            ),
            {"id": str(uuid.UUID(int=1))},
        )
        db_session.commit()

        result = db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
                values
                    (:tomador_id, 'emprestimo', 15000, 2.5, 'PRICE', 12, 'registrada', 'REG-AUD')
                returning id
                """
            ),
            {"tomador_id": str(tomador_autorizado)},
        )
        db_session.commit()
        op_id = result.scalar_one()

        ativar_operacao(db_session, op_id, usuario_id=str(uuid.UUID(int=1)))

        response = authed_client.get("/api/auditoria")

        assert response.status_code == 200
        body = response.json()
        assert body["integro"] is True
        assert len(body["eventos"]) == 1
        evento = body["eventos"][0]
        assert evento["evento_tipo"] == "ativacao_operacao"
        assert evento["usuario_nome"] == "Ana"
        assert evento["current_hash"] is not None
        assert evento["prev_hash"] is None  # primeiro evento da cadeia
