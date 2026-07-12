"""
Autenticação e segurança — Supabase Auth + JWT validation.

Esperado que o frontend (painel de operadores) faça login via Supabase Auth,
obtenha um JWT, e o inclua em Authorization: Bearer <jwt> em cada requisição.
A API valida o JWT e extrai user_id (ou sub do JWT) para contexto de auditoria.
"""

import os
from typing import Any, Optional

import jwt
from pydantic import BaseModel


class JWTConfig:
    """Configuração de JWT/Supabase Auth."""

    # Em produção, puxar da variável SUPABASE_JWT_SECRET
    # Para dev, usar uma secret comum (não-segura!)
    jwt_secret: str = os.environ.get("SUPABASE_JWT_SECRET", "dev-secret-key-change-in-prod")
    jwt_algorithm: str = "HS256"
    jwt_audience: Optional[str] = os.environ.get("SUPABASE_JWT_AUDIENCE", None)


class CurrentUser(BaseModel):
    """Usuário autenticado extraído do JWT."""

    user_id: str  # sub do JWT (UUID do usuário no Supabase Auth)
    email: Optional[str] = None
    papel: Optional[str] = None  # admin, operador (custom claim)


def decode_jwt(token: str) -> dict[str, Any]:
    """Decodifica e valida JWT."""
    try:
        payload = jwt.decode(
            token,
            JWTConfig.jwt_secret,
            algorithms=[JWTConfig.jwt_algorithm],
            audience=JWTConfig.jwt_audience,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expirado")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Token inválido: {e}")


def extract_user_from_jwt(token: str) -> CurrentUser:
    """Extrai CurrentUser do JWT."""
    payload = decode_jwt(token)

    # Supabase padrão: sub é o user_id
    user_id: str = payload.get("sub", "")
    if not user_id:
        raise ValueError("Token sem 'sub' (user_id)")

    email: Optional[str] = payload.get("email")
    # Papel pode ser custom claim no JWT, ex: {"papel": "operador"}
    papel: Optional[str] = payload.get("papel")

    return CurrentUser(user_id=user_id, email=email, papel=papel)
