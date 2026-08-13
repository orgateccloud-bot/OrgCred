"""
Testes de app.core.security — validação de JWT e resolução de usuário
(Zero-Trust: o token prova identidade, mas papel/ativo vêm do banco, não
de claims do JWT).

Inclui também o endurecimento de EXPOSIÇÃO (passo 14): o que a aplicação
serve a quem não apresentou credencial nenhuma — esquema da API, métricas
internas — e o teto de requisições por origem.
"""

import time
import uuid
from contextlib import contextmanager
from typing import Generator, Optional

import jwt
import pytest
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import PermissaoNegada, TokenAusente, TokenInvalido
from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.main import LIMITE_ESCRITA, criar_app
from app.main import app as app_desenvolvimento
from app.models import Usuario


def _gerar_token(sub: str, secret: Optional[str] = None, exp_delta: int = 3600) -> str:
    claims = {"sub": sub, "exp": int(time.time()) + exp_delta}
    return jwt.encode(claims, secret or settings.supabase_jwt_secret, algorithm="HS256")


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _criar_usuario(db_session: Session, papel: str = "operador", ativo: bool = True) -> uuid.UUID:
    result = db_session.execute(
        text(
            """
            insert into usuario (email, nome, papel, ativo)
            values (:email, 'Usuário Teste', :papel, :ativo)
            returning id
            """
        ),
        {"email": f"{uuid.uuid4().hex[:8]}@orgatec.com", "papel": papel, "ativo": ativo},
    )
    db_session.commit()
    return result.scalar_one()


class TestGetCurrentUser:
    def test_sem_credentials_levanta_token_ausente(self, db_session: Session) -> None:
        with pytest.raises(TokenAusente):
            get_current_user(credentials=None, db=db_session)

    def test_token_valido_com_usuario_ativo_retorna_usuario(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session, papel="operador", ativo=True)
        token = _gerar_token(sub=str(usuario_id))

        usuario = get_current_user(credentials=_credentials(token), db=db_session)

        assert usuario.id == usuario_id
        assert usuario.papel == "operador"

    def test_token_expirado_levanta_token_invalido(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session)
        token = _gerar_token(sub=str(usuario_id), exp_delta=-3600)

        with pytest.raises(TokenInvalido, match="expirado"):
            get_current_user(credentials=_credentials(token), db=db_session)

    def test_token_com_secret_errada_levanta_token_invalido(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session)
        token = _gerar_token(sub=str(usuario_id), secret="secret-errada")

        with pytest.raises(TokenInvalido):
            get_current_user(credentials=_credentials(token), db=db_session)

    def test_token_sem_sub_levanta_token_invalido(self, db_session: Session) -> None:
        claims = {"exp": int(time.time()) + 3600}
        token = jwt.encode(claims, settings.supabase_jwt_secret, algorithm="HS256")

        with pytest.raises(TokenInvalido, match="sub"):
            get_current_user(credentials=_credentials(token), db=db_session)

    def test_token_com_usuario_inexistente_levanta_permissao_negada(
        self, db_session: Session
    ) -> None:
        token = _gerar_token(sub=str(uuid.uuid4()))

        with pytest.raises(PermissaoNegada, match="não encontrado"):
            get_current_user(credentials=_credentials(token), db=db_session)

    def test_token_com_usuario_inativo_levanta_permissao_negada(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session, ativo=False)
        token = _gerar_token(sub=str(usuario_id))

        with pytest.raises(PermissaoNegada, match="inativo"):
            get_current_user(credentials=_credentials(token), db=db_session)


class TestGetOperadorUser:
    def test_papel_operador_passa(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session, papel="operador")
        token = _gerar_token(sub=str(usuario_id))
        usuario = get_current_user(credentials=_credentials(token), db=db_session)

        resultado = get_operador_user(current_user=usuario)

        assert resultado.id == usuario_id

    def test_papel_admin_tambem_passa(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session, papel="admin")
        token = _gerar_token(sub=str(usuario_id))
        usuario = get_current_user(credentials=_credentials(token), db=db_session)

        resultado = get_operador_user(current_user=usuario)

        assert resultado.id == usuario_id

    def test_papel_desconhecido_levanta_permissao_negada(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session, papel="convidado")
        token = _gerar_token(sub=str(usuario_id))
        usuario = get_current_user(credentials=_credentials(token), db=db_session)

        with pytest.raises(PermissaoNegada):
            get_operador_user(current_user=usuario)


class TestGetAdminUser:
    def test_papel_admin_passa(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session, papel="admin")
        token = _gerar_token(sub=str(usuario_id))
        usuario = get_current_user(credentials=_credentials(token), db=db_session)

        resultado = get_admin_user(current_user=usuario)

        assert resultado.id == usuario_id

    def test_papel_operador_levanta_permissao_negada(self, db_session: Session) -> None:
        usuario_id = _criar_usuario(db_session, papel="operador")
        token = _gerar_token(sub=str(usuario_id))
        usuario = get_current_user(credentials=_credentials(token), db=db_session)

        with pytest.raises(PermissaoNegada, match="administradores"):
            get_admin_user(current_user=usuario)


# ---------------------------------------------------------------------------
# Endurecimento de exposição (passo 14)
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_producao(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Aplicação montada como em produção.

    `settings.environment` é lido dentro de `criar_app()`, e não no import do
    módulo, exatamente para que este teste possa interrogar a configuração
    real de produção em vez de uma aproximação.
    """
    monkeypatch.setattr(settings, "environment", "production")
    return criar_app()


@contextmanager
def _cliente(app: FastAPI, db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient com o banco apontado para a transação do teste.

    Sem o override, `get_db` abriria conexão contra `settings.database_url`
    (localhost, o default de desenvolvimento) — e nesta máquina cada tentativa
    de conexão por 'localhost' custa 21 segundos até falhar.
    """
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


class TestEsquemaDaAPIEmProducao:
    """/docs, /redoc e /openapi.json respondiam 200 sem credencial em
    produção: o mapa completo da API — todo caminho, todo campo de todo
    schema — entregue a quem só sabia o endereço."""

    def test_openapi_desativado_em_producao(self, app_producao: FastAPI) -> None:
        cliente = TestClient(app_producao)

        assert cliente.get("/openapi.json").status_code == 404
        assert app_producao.openapi_url is None

    def test_docs_e_redoc_desativados_em_producao(self, app_producao: FastAPI) -> None:
        cliente = TestClient(app_producao)

        assert cliente.get("/docs").status_code == 404
        assert cliente.get("/redoc").status_code == 404
        # As duas linhas acima sozinhas NÃO provam que `docs_url`/`redoc_url`
        # estão desligados: o FastAPI registra as rotas do Swagger e do ReDoc
        # dentro de `if self.openapi_url and self.docs_url` (applications.py),
        # então com `openapi_url=None` elas somem de qualquer jeito e o 404
        # apareceria mesmo se alguém religasse `docs_url` aqui. Verificado por
        # mutação: religar só `docs_url` deixava o teste verde. As asserções
        # abaixo travam a configuração em si, para que uma decisão futura de
        # reexpor `/openapi.json` (atrás de credencial, digamos) não reabra o
        # Swagger de brinde.
        assert app_producao.docs_url is None
        assert app_producao.redoc_url is None

    def test_continuam_ligados_em_desenvolvimento(self) -> None:
        """Não é para quebrar o fluxo local: o cliente Hey API do frontend é
        gerado a partir de /openapi.json contra o backend de desenvolvimento.
        Desativar nos dois ambientes teria trocado uma exposição por uma
        quebra silenciosa da geração de código."""
        cliente = TestClient(app_desenvolvimento)

        resposta = cliente.get("/openapi.json")

        assert resposta.status_code == 200
        assert "/api/auditoria" in resposta.json()["paths"]
        assert cliente.get("/docs").status_code == 200


class TestMetricsProtegido:
    """/metrics respondia 200 sem credencial: contadores de operações
    ativadas, de bloqueios por SQLSTATE e de falhas de autenticação —
    volume de negócio e postura de risco deduzíveis por qualquer um."""

    def test_sem_credencial_e_recusado(self, db_session: Session) -> None:
        with _cliente(app_desenvolvimento, db_session) as cliente:
            resposta = cliente.get("/metrics")

            assert resposta.status_code == 401
            assert resposta.json()["codigo"] == "TOKEN_AUSENTE"
            # E, principalmente, nada de métrica no corpo.
            assert "orgcred_" not in resposta.text

    def test_sem_credencial_e_recusado_tambem_em_producao(
        self, app_producao: FastAPI, db_session: Session
    ) -> None:
        with _cliente(app_producao, db_session) as cliente:
            assert cliente.get("/metrics").status_code == 401

    def test_com_credencial_devolve_o_texto_prometheus(self, db_session: Session) -> None:
        operador = Usuario(
            id=uuid.uuid4(),
            email="scraper@orgatec.com",
            nome="Conta de Serviço",
            papel="operador",
            ativo=True,
        )
        app_desenvolvimento.dependency_overrides[get_current_user] = lambda: operador
        try:
            with _cliente(app_desenvolvimento, db_session) as cliente:
                resposta = cliente.get("/metrics")

                assert resposta.status_code == 200
                assert resposta.headers["content-type"].startswith("text/plain")
                assert "orgcred_operacoes_ativadas_total" in resposta.text
        finally:
            app_desenvolvimento.dependency_overrides.clear()


class TestRateLimiting:
    """O `Limiter` do slowapi estava instanciado e nunca ligado: nenhuma rota
    decorada, middleware não registrado. A dependência existia, a proteção
    não."""

    def test_limite_de_escrita_dispara_429(
        self, app_producao: FastAPI, db_session: Session
    ) -> None:
        teto = int(LIMITE_ESCRITA.split("/")[0])

        with _cliente(app_producao, db_session) as cliente:
            # As requisições nem precisam ser bem-sucedidas: o limitador
            # conta ANTES de a rota rodar, que é o ponto — quem martela o
            # endpoint com token inválido também é freado.
            for _ in range(teto):
                assert cliente.post("/api/operacoes", json={}).status_code == 401

            estourada = cliente.post("/api/operacoes", json={})

            assert estourada.status_code == 429
            assert estourada.json()["codigo"] == "OC429"
            assert estourada.headers["retry-after"] == "60"
            # A resposta não conta ao atacante qual é a janela — o default do
            # slowapi devolvia "Rate limit exceeded: 30 per 1 minute".
            assert str(teto) not in estourada.text

    def test_leitura_nao_cai_no_teto_de_escrita(
        self, app_producao: FastAPI, db_session: Session
    ) -> None:
        """Leitura e escrita são baldes separados, com números separados. Se
        compartilhassem o teto, o polling do painel derrubaria a operação."""
        teto_escrita = int(LIMITE_ESCRITA.split("/")[0])

        with _cliente(app_producao, db_session) as cliente:
            for _ in range(teto_escrita + 5):
                assert cliente.get("/health").status_code == 200

    def test_desligado_em_desenvolvimento(self, db_session: Session) -> None:
        """Em desenvolvimento o limitador fica desligado de propósito: a
        suíte e o e2e disparam centenas de requisições da mesma origem para o
        mesmo caminho, e um 429 no meio disso seria um vermelho falso."""
        limiter = app_desenvolvimento.state.limiter

        assert limiter.enabled is False
