"""
Testes de app.core.security — validação de JWT e resolução de usuário
(Zero-Trust: o token prova identidade, mas papel/ativo vêm do banco, não
de claims do JWT).
"""

import time
import uuid
from typing import Optional

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import PermissaoNegada, TokenAusente, TokenInvalido
from app.core.security import get_admin_user, get_current_user, get_operador_user


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
