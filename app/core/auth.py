"""
Dependencies FastAPI para autenticação e autorização.

Usado como Depends() nos endpoints para garantir JWT válido e autorização.
"""

from typing import Optional

from fastapi import Depends, Header

from app.core.exceptions import (
    PermissaoNegada,
    TokenAusente,
    TokenInvalido,
)
from app.core.security import CurrentUser, extract_user_from_jwt


async def get_current_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    """
    Dependency: extrai e valida JWT do header Authorization.

    Uso: @app.get("/endpoint")
         def endpoint(user: CurrentUser = Depends(get_current_user)):
             ...
    """
    if not authorization:
        raise TokenAusente()

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise TokenAusente()

    token = parts[1]
    try:
        user = extract_user_from_jwt(token)
    except ValueError as e:
        raise TokenInvalido(str(e))

    return user


async def require_operador(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Dependency: permite apenas papel 'operador' ou 'admin'."""
    if user.papel not in ("operador", "admin"):
        raise PermissaoNegada(
            f"Operação requer papel 'operador' ou 'admin', você tem '{user.papel}'"
        )
    return user


async def require_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Dependency: permite apenas papel 'admin'."""
    if user.papel != "admin":
        raise PermissaoNegada(f"Operação requer papel 'admin', você tem '{user.papel}'")
    return user
