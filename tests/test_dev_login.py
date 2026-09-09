"""
Login de conveniência de desenvolvimento (app/routers/dev.py).

O QUE PRECISA PROVAR, em ordem de gravidade:
1. QUE ELE NÃO EXISTE EM PRODUÇÃO. É a garantia inteira do bypass: em produção
   a rota não é montada, então /api/dev/login responde 404. Se isto quebrar, um
   endpoint que emite token sem senha estaria no ar em produção.
2. Que no dev ele emite um token que o próprio get_current_user aceita, para um
   usuário que JÁ EXISTE — não cria usuário nem aceita e-mail arbitrário.
"""

import uuid
from contextlib import contextmanager
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.main import criar_app


@contextmanager
def _cliente(app: FastAPI, db_session: Session) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _criar_usuario(db_session: Session, email: str, papel: str = "admin") -> uuid.UUID:
    return db_session.execute(
        text("""
        insert into usuario (id, email, nome, papel)
        values (gen_random_uuid(), :e, 'Dev', :p) returning id
        """),
        {"e": email, "p": papel},
    ).scalar_one()


def test_dev_login_nao_existe_em_producao(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A garantia é a AUSÊNCIA da rota, não uma checagem interna."""
    monkeypatch.setattr(settings, "environment", "production")
    app = criar_app()
    with _cliente(app, db_session) as cliente:
        resp = cliente.post("/api/dev/login", json={"email": "admin@orgcred.local"})
    assert resp.status_code == 404


def test_dev_login_emite_token_aceito_para_usuario_existente(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    email = f"dev-{uuid.uuid4().hex[:8]}@orgcred.local"
    uid = _criar_usuario(db_session, email, papel="admin")
    db_session.commit()

    app = criar_app()
    with _cliente(app, db_session) as cliente:
        resp = cliente.post("/api/dev/login", json={"email": email})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        assert resp.json()["user"]["id"] == str(uid)

        # O token emitido é aceito pelo caminho real de autenticação.
        me = cliente.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == email
        assert me.json()["papel"] == "admin"


def test_dev_login_recusa_email_desconhecido(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escopo: só entra quem já é usuário — não cria conta nem aceita qualquer
    e-mail."""
    monkeypatch.setattr(settings, "environment", "development")
    app = criar_app()
    with _cliente(app, db_session) as cliente:
        resp = cliente.post("/api/dev/login", json={"email": "ninguem@lugar-nenhum.com"})
    assert resp.status_code == 404
