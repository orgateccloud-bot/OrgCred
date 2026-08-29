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
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/me", tags=["me"])


class MeOut(BaseModel):
    id: UUID
    email: str
    nome: str
    papel: str


@router.get("", response_model=MeOut)
def get_me(
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeOut:
    # O aceite do convite ao portal (migration 031) preenche aqui, e não numa
    # rota do portal: /me é o primeiro request autenticado de QUALQUER fluxo
    # de entrada (o frontend o chama para decidir a home), e o portal
    # permanece sem verbo de escrita, como o cabeçalho dele promete. Não é o
    # cliente agindo sobre o crédito — é o sistema registrando o fato "o
    # convidado entrou". O WHERE em `aceito_em is null` torna o update
    # idempotente; o trigger OC027 garante que preenchido não se reescreve.
    if user.papel == "tomador":
        db.execute(
            text("""
            update convite_portal set aceito_em = clock_timestamp()
             where usuario_id = :u and aceito_em is null
            """),
            {"u": str(user.id)},
        )
        db.commit()

    return MeOut(
        id=user.id,  # type: ignore[arg-type]
        email=user.email,  # type: ignore[arg-type]
        nome=user.nome,  # type: ignore[arg-type]
        papel=user.papel,  # type: ignore[arg-type]
    )
