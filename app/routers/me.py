"""Router: identidade do usuário autenticado.

Fecha o gap documentado na store do frontend (useAppStore): `papel`/`nome`
vêm da tabela usuario, não do token Supabase — sem este endpoint a UI não
tinha como saber o papel para decidir o que exibir. O enforcement real de
papel continua no backend a cada request (Zero-Trust); isto é só leitura
informativa para a UI.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_current_user
from app.models import Usuario


router = APIRouter(prefix="/me", tags=["me"])


class MeOut(BaseModel):
    id: UUID
    email: str
    nome: str
    papel: str


@router.get("", response_model=MeOut)
def get_me(user: Usuario = Depends(get_current_user)) -> MeOut:
    return MeOut(
        id=user.id,  # type: ignore[arg-type]
        email=user.email,  # type: ignore[arg-type]
        nome=user.nome,  # type: ignore[arg-type]
        papel=user.papel,  # type: ignore[arg-type]
    )
