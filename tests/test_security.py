"""Testes de app.core.security — decodificação e validação de JWT."""

import time

import jwt
import pytest

from app.core.security import JWTConfig, extract_user_from_jwt


def _gerar_token(payload: dict, secret: str | None = None, exp_delta: int = 3600) -> str:
    claims = {**payload, "exp": int(time.time()) + exp_delta}
    return jwt.encode(claims, secret or JWTConfig.jwt_secret, algorithm=JWTConfig.jwt_algorithm)


class TestExtractUserFromJWT:
    def test_extrai_usuario_valido(self) -> None:
        token = _gerar_token({"sub": "user-123", "email": "op@orgatec.com", "papel": "operador"})

        user = extract_user_from_jwt(token)

        assert user.user_id == "user-123"
        assert user.email == "op@orgatec.com"
        assert user.papel == "operador"

    def test_token_sem_sub_falha(self) -> None:
        token = _gerar_token({"email": "op@orgatec.com"})

        with pytest.raises(ValueError, match="sub"):
            extract_user_from_jwt(token)

    def test_token_expirado_falha(self) -> None:
        token = _gerar_token({"sub": "user-123"}, exp_delta=-3600)

        with pytest.raises(ValueError, match="expirado"):
            extract_user_from_jwt(token)

    def test_token_com_secret_errada_falha(self) -> None:
        token = _gerar_token({"sub": "user-123"}, secret="secret-errada")

        with pytest.raises(ValueError, match="inválido"):
            extract_user_from_jwt(token)

    def test_token_sem_papel_eh_opcional(self) -> None:
        token = _gerar_token({"sub": "user-123"})

        user = extract_user_from_jwt(token)

        assert user.papel is None
