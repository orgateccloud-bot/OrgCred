"""
Testes do router HTTP /operacoes — valida tradução de exceção de domínio
para status HTTP (404/409/422) e enforcement de autenticação/autorização.
"""

import uuid
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_operador_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.conftest import confirmar_registro


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
    """Client com autenticação mockada (papel operador) — overrides as duas
    dependencies que exigem usuário: get_current_user (aplicada a nível de
    router em app.main) e get_operador_user (aplicada no endpoint de
    ativação)."""
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador Teste", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    app.dependency_overrides[get_operador_user] = lambda: operador
    return client


@pytest.fixture()
def client_sem_papel_operador(client: TestClient) -> TestClient:
    """Client autenticado, mas com papel que não é operador nem admin — só
    sobrescreve get_current_user (a checagem de papel em get_operador_user
    roda de verdade, para provar que a autorização por papel é enforced)."""
    convidado = Usuario(
        id=uuid.uuid4(),
        email="convidado@orgatec.com",
        nome="Convidado",
        papel="convidado",
        ativo=True,
    )
    app.dependency_overrides[get_current_user] = lambda: convidado
    return client


class TestAtivarOperacaoSemAutenticacao:
    def test_sem_authorization_header_retorna_401(
        self, client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        response = client.post(f"/api/operacoes/{uuid.uuid4()}/ativar")
        assert response.status_code == 401
        assert response.json()["codigo"] == "TOKEN_AUSENTE"


class TestAtivarOperacaoSemPapelAdequado:
    def test_papel_sem_permissao_retorna_403(self, client_sem_papel_operador: TestClient) -> None:
        response = client_sem_papel_operador.post(f"/api/operacoes/{uuid.uuid4()}/ativar")
        assert response.status_code == 403
        assert response.json()["codigo"] == "PERMISSAO_NEGADA"


class TestAtivarOperacaoComPermissao:
    def test_operacao_inexistente_retorna_404(self, authed_client: TestClient) -> None:
        response = authed_client.post(f"/api/operacoes/{uuid.uuid4()}/ativar")
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
        confirmar_registro(db_session, op_id)

        response = authed_client.post(f"/api/operacoes/{op_id}/ativar")

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
        db_session.commit()
        primeira_id = db_session.execute(
            text("select id from operacao_credito where registro_entidade_ref = 'REG-A'")
        ).scalar_one()
        confirmar_registro(db_session, primeira_id)
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
        # Registro confirmado também na segunda: sem ele o bloqueio viria de
        # OC004 e o teste deixaria de provar o que promete (OC001).
        confirmar_registro(db_session, op_id)

        response = authed_client.post(f"/api/operacoes/{op_id}/ativar")

        assert response.status_code == 422
        body = response.json()
        # RegraNegocioViolada propaga para o exception_handler global
        # (app/main.py) — formato plano, igual ao resto da API.
        assert body["codigo"] == "OC001"


class TestListarOperacoes:
    def test_sem_autenticacao_retorna_401(self, client: TestClient) -> None:
        response = client.get("/api/operacoes")
        assert response.status_code == 401

    def test_sem_operacoes_retorna_lista_vazia(self, authed_client: TestClient) -> None:
        response = authed_client.get("/api/operacoes")
        assert response.status_code == 200
        assert response.json() == []

    def test_lista_operacoes_mais_recente_primeiro(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
    ) -> None:
        db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref,
                     created_at)
                values
                    (:tomador_id, 'emprestimo', 10000, 2.5, 'PRICE', 12, 'proposta', null,
                     now() - interval '1 day'),
                    (:tomador_id, 'financiamento', 20000, 3.0, 'SAC', 24, 'registrada', 'REG-X',
                     now())
                """
            ),
            {"tomador_id": str(tomador_autorizado)},
        )
        db_session.commit()

        response = authed_client.get("/api/operacoes")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert body[0]["tipo"] == "financiamento"
        assert body[0]["tomador_razao_social"] == "Padaria Teste ME"
        assert body[1]["tipo"] == "emprestimo"


class TestGetParcelas:
    """GET /operacoes/{id}/parcelas — a agenda emitida na ativação."""

    def test_exige_autenticacao(self, client: TestClient) -> None:
        response = client.get(f"/api/operacoes/{uuid.uuid4()}/parcelas")
        assert response.status_code == 401

    def test_operacao_inexistente_404(self, authed_client: TestClient) -> None:
        response = authed_client.get(f"/api/operacoes/{uuid.uuid4()}/parcelas")
        assert response.status_code == 404

    def test_operacao_sem_agenda_retorna_lista_vazia(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
    ) -> None:
        """Não ativada ainda não tem agenda — isso é estado legítimo do
        ciclo de vida, não erro, então 200 com lista vazia e não 404."""
        op_id = db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
                values (:t, 'emprestimo', 12000, 2.5, 'PRICE', 12, 'registrada', 'REG-X')
                returning id
                """
            ),
            {"t": str(tomador_autorizado)},
        ).scalar_one()
        db_session.commit()

        response = authed_client.get(f"/api/operacoes/{op_id}/parcelas")

        assert response.status_code == 200
        body = response.json()
        assert body["parcelas"] == []
        assert body["total_geral"] == "0"

    def test_agenda_apos_ativacao(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
                values (:t, 'emprestimo', 12000, 0, 'PRICE', 12, 'registrada', 'REG-X')
                returning id
                """
            ),
            {"t": str(tomador_autorizado)},
        ).scalar_one()
        db_session.commit()
        confirmar_registro(db_session, op_id)

        assert authed_client.post(f"/api/operacoes/{op_id}/ativar").status_code == 200

        response = authed_client.get(f"/api/operacoes/{op_id}/parcelas")

        assert response.status_code == 200
        body = response.json()
        assert len(body["parcelas"]) == 12
        assert body["sistema_amortizacao"] == "PRICE"
        # Taxa zero: total geral = principal, sem juros.
        assert Decimal(body["total_amortizacao"]) == Decimal("12000.00")
        assert Decimal(body["total_juros"]) == Decimal("0")
        assert Decimal(body["total_geral"]) == Decimal("12000.00")
        assert body["parcelas"][0]["numero"] == 1
        assert body["parcelas"][0]["status"] == "aberta"
