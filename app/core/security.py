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
        # Supabase utiliza HS256 por padrão.
        #
        # `require=["exp", "sub"]` NÃO é redundante com `verify_exp`: sem ele,
        # um token assinado com o segredo mas SEM claim `exp` é aceito e NUNCA
        # expira — a assinatura confere, e `verify_exp` só checa um `exp` que
        # exista. Exigir a presença fecha o token eterno. `sub` idem: sem ele o
        # `payload.get("sub")` abaixo cairia num TokenInvalido genérico; exigido
        # aqui, a recusa é no lugar certo.
        #
        # ISSUER verificado SÓ QUANDO CONFIGURADO. Supabase assina com
        # `iss = {url}/auth/v1`. Em produção `supabase_url` pode ainda não estar
        # setada (a chave de assinatura basta para validar), e exigir o issuer
        # sem ele configurado recusaria todo token — fail-closed pelo motivo
        # errado. Com a URL presente, passamos o issuer esperado ao PyJWT e um
        # token de OUTRO projeto Supabase (mesmo que por acaso compartilhasse o
        # segredo) é recusado. `aud` segue não verificado: o valor default do
        # Supabase ('authenticated') é estável, mas verificá-lo sem necessidade
        # só adicionaria uma forma de quebrar sem fechar nada que o issuer não
        # feche.
        # `issuer=None` faz o PyJWT NÃO verificar o emissor (comportamento de
        # hoje, com supabase_url vazia). Com a URL setada, passamos o issuer
        # esperado e o PyJWT recusa qualquer outro.
        emissor_esperado = settings.supabase_url.strip()
        issuer = f"{emissor_esperado}/auth/v1" if emissor_esperado else None
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False, "require": ["exp", "sub"]},
            issuer=issuer,
        )
    except jwt.ExpiredSignatureError:
        raise TokenInvalido("Token expirado")
    except jwt.MissingRequiredClaimError:
        raise TokenInvalido("Token sem claim obrigatória (exp/sub)")
    except jwt.InvalidIssuerError:
        raise TokenInvalido("Token de emissor não reconhecido")
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
