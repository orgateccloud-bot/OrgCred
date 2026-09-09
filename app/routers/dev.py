"""Router de conveniência de DESENVOLVIMENTO — login sem Supabase.

POR QUE EXISTE: a autenticação real é delegada ao Supabase Auth, e no ambiente
de desenvolvimento não há um projeto Supabase de pé. Sem isto, o formulário de
login (`signInWithPassword`) não tem contra o que autenticar, e ninguém entra no
sistema local sem forjar um token à mão.

POR QUE É SEGURO: este router é montado APENAS quando
`settings.environment != "production"` (ver app/main.py). Em produção a rota não
existe — não é uma checagem que se pode esquecer de fazer, é a ausência do
endpoint. Duplo portão: o frontend só chama este caminho sob `import.meta.env.DEV`
(morto no bundle de produção), e o backend só o registra fora de produção.

O QUE ELE FAZ, E O QUE NÃO FAZ: emite um JWT assinado com o mesmo segredo que o
resto do sistema valida, para um usuário que JÁ EXISTE na tabela `usuario`. Não
cria usuário, não aceita e-mail arbitrário, não recebe senha — no dev, qualquer
senha "vale" porque a senha real vive no Supabase, que está ausente. O papel
continua vindo do banco a cada request (Zero-Trust), exatamente como no fluxo
real: este endpoint só encurta a obtenção do token, não afrouxa a autorização.
"""

import time
from typing import Any, Dict

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/dev", tags=["dev"])

# Oito horas: uma jornada de trabalho, para não expirar no meio de um teste
# manual. É token de desenvolvimento; a folga não custa nada aqui.
_VALIDADE_SEGUNDOS = 8 * 3600


class DevLoginIn(BaseModel):
    email: str


class DevLoginOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int
    token_type: str
    user: Dict[str, Any]


@router.post("/login", response_model=DevLoginOut)
def dev_login(body: DevLoginIn, db: Session = Depends(get_db)) -> DevLoginOut:
    usuario = (
        db.query(Usuario).filter(Usuario.email == body.email, Usuario.ativo.is_(True)).one_or_none()
    )
    if usuario is None:
        # Escopo deliberado: só entra quem já é usuário. A mensagem cita os
        # e-mails semeados para o desenvolvedor não adivinhar.
        raise HTTPException(
            status_code=404,
            detail=(
                f"Nenhum usuário ativo com e-mail {body.email!r}. "
                "No dev, use um e-mail já semeado (ex.: admin@orgcred.local)."
            ),
        )

    agora = int(time.time())
    exp = agora + _VALIDADE_SEGUNDOS
    token = jwt.encode(
        {
            "sub": str(usuario.id),
            "email": usuario.email,
            "exp": exp,
            "iat": agora,
            "aud": "authenticated",
            "role": "authenticated",
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )
    return DevLoginOut(
        access_token=token,
        refresh_token="dev-no-refresh",
        expires_at=exp,
        token_type="bearer",
        user={"id": str(usuario.id), "email": usuario.email},
    )
