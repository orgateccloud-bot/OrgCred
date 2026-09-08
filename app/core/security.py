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


def get_painel_user(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Portão do PAINEL da ESC: admin ou operador, nunca tomador.

    É a dependência de nível de router de tudo que é operação interna. A
    diferença para `get_operador_user` é o propósito, não o efeito hoje (os dois
    aceitam o mesmo conjunto): esta existe para ser o GATE que fecha o painel a
    um login de tomador ANTES de qualquer rota individual, mesmo as que por
    dentro só pedem `get_current_user`. Sem ela, um tomador autenticado
    alcançaria as leituras de capital, auditoria e compliance que não exigem
    papel de operador — o vazamento que o portal existe para não abrir.
    """
    if current_user.papel not in ("operador", "admin"):
        raise PermissaoNegada("Área restrita à equipe da ESC.")
    return current_user


def get_tomador_user(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Portão do PORTAL: papel 'tomador', com vínculo a uma empresa.

    O `tomador_id is None` nunca deveria acontecer — o CHECK
    `usuario_papel_vinculo_coerente` (migration 031) garante no banco que todo
    tomador tem vínculo. A checagem aqui é defesa em profundidade e uma verdade
    para o type checker: as rotas do portal filtram por `user.tomador_id`, e um
    None ali seria um filtro que casa tudo.
    """
    if current_user.papel != "tomador" or current_user.tomador_id is None:
        raise PermissaoNegada("Área restrita aos tomadores com acesso ao portal.")
    return current_user
