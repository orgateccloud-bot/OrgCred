"""
Autenticação e segurança — Supabase Auth + JWT validation (Zero-Trust).

O frontend faz login via Supabase Auth, obtém um JWT, e o inclui em Authorization: Bearer <jwt> em cada requisição.
A API valida o JWT e fornece a dependência get_current_user.
"""

from typing import Optional

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import PermissaoNegada, TokenAusente, TokenInvalido
from app.db import get_db
from app.models import Usuario


security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Usuario:
    """Dependency para extrair e validar o usuário do JWT (Zero-Trust)."""
    if not credentials:
        raise TokenAusente()

    token = credentials.credentials
    try:
        # Supabase utiliza HS256 por padrão
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise TokenInvalido("Token expirado")
    except jwt.PyJWTError:
        raise TokenInvalido("Assinatura inválida")

    user_id = payload.get("sub")
    if not user_id:
        raise TokenInvalido("Token sem 'sub'")

    # Convert str sub to UUID for querying the Usuario table
    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()

    if not usuario:
        raise PermissaoNegada("Usuário não encontrado")
    if not usuario.ativo:
        raise PermissaoNegada("Usuário inativo")

    return usuario


def get_admin_user(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependency para restringir rotas apenas a administradores."""
    if current_user.papel != "admin":
        raise PermissaoNegada("Ação restrita a administradores")
    return current_user


def get_operador_user(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependency para restringir rotas a operadores ou administradores."""
    if current_user.papel not in ("operador", "admin"):
        raise PermissaoNegada(
            f"Operação requer papel 'operador' ou 'admin', você tem '{current_user.papel}'"
        )
    return current_user
