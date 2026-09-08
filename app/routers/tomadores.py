"""
Router: cadastro e consulta de tomadores.

O gate geográfico (OC002) é enforced pelo trigger na ativação da operação;
`municipio_autorizado` aqui é dado cadastral — marcar como autorizado é
decisão operacional (admin), não validação automática. KYC (Receita,
listas restritivas) segue pendente — ver app/routers/compliance.py.
"""

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.convites import (
    ConviteFalhou,
    ConvitesNaoConfigurados,
    EmailJaRegistrado,
    convidar_no_supabase,
)
from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.models import Tomador, Usuario


router = APIRouter(prefix="/tomadores", tags=["tomadores"])


class TomadorOut(BaseModel):
    id: UUID
    cnpj: str
    razao_social: str
    porte: str
    municipio: str
    uf: str
    municipio_autorizado: bool
    created_at: datetime


class TomadorOperacaoResumoOut(BaseModel):
    id: UUID
    tipo: str
    valor_principal: str
    status: str
    created_at: datetime


class TomadorDetailOut(TomadorOut):
    operacoes: List[TomadorOperacaoResumoOut]


class CriarTomadorIn(BaseModel):
    cnpj: str = Field(pattern=r"^\d{14}$", description="Somente dígitos")
    razao_social: str = Field(min_length=1, max_length=255)
    porte: Literal["ME", "EPP"]
    municipio: str = Field(min_length=1, max_length=255)
    uf: str = Field(pattern=r"^[A-Z]{2}$")


class AtualizarAutorizacaoIn(BaseModel):
    municipio_autorizado: bool


@router.get("", response_model=List[TomadorOut])
def get_tomadores(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[TomadorOut]:
    rows = db.query(Tomador).order_by(Tomador.razao_social).all()
    return [TomadorOut.model_validate(t, from_attributes=True) for t in rows]


@router.get("/{tomador_id}", response_model=TomadorDetailOut)
def get_tomador(
    tomador_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> TomadorDetailOut:
    tomador: Optional[Tomador] = db.query(Tomador).filter(Tomador.id == tomador_id).one_or_none()
    if tomador is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")

    operacoes = db.execute(
        text("""
        select id, tipo, valor_principal, status, created_at
        from operacao_credito where tomador_id = :tomador_id
        order by created_at desc
    """),
        {"tomador_id": str(tomador_id)},
    ).all()

    base = TomadorOut.model_validate(tomador, from_attributes=True)
    return TomadorDetailOut(
        **base.model_dump(),
        operacoes=[
            TomadorOperacaoResumoOut(
                id=op.id,
                tipo=op.tipo,
                valor_principal=str(op.valor_principal),
                status=op.status,
                created_at=op.created_at,
            )
            for op in operacoes
        ],
    )


@router.post("", response_model=TomadorOut, status_code=201)
def post_criar_tomador(
    body: CriarTomadorIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> TomadorOut:
    """Cadastro nasce com municipio_autorizado=false — a autorização do gate
    geográfico é ato separado, restrito a admin (PATCH /autorizacao)."""
    tomador = Tomador(
        id=uuid4(),
        cnpj=body.cnpj,
        razao_social=body.razao_social,
        porte=body.porte,
        municipio=body.municipio,
        uf=body.uf,
        municipio_autorizado=False,
    )
    db.add(tomador)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"CNPJ {body.cnpj} já cadastrado.")
    db.refresh(tomador)
    return TomadorOut.model_validate(tomador, from_attributes=True)


@router.patch("/{tomador_id}/autorizacao", response_model=TomadorOut)
def patch_autorizacao(
    tomador_id: UUID,
    body: AtualizarAutorizacaoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> TomadorOut:
    """Liga/desliga a autorização do município (gate OC002). Admin only:
    é a chave que permite ativar crédito para o tomador."""
    tomador: Optional[Tomador] = db.query(Tomador).filter(Tomador.id == tomador_id).one_or_none()
    if tomador is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")
    tomador.municipio_autorizado = body.municipio_autorizado  # type: ignore[assignment]
    db.commit()
    db.refresh(tomador)
    return TomadorOut.model_validate(tomador, from_attributes=True)


# ---------------------------------------------------------------------------
# Acesso ao portal (migration 031): convidar o tomador e ler a trilha
# ---------------------------------------------------------------------------


class ConvidarPortalIn(BaseModel):
    # Validação de FORMA, não de existência — quem decide se o e-mail é real é
    # a entrega do convite. Sem EmailStr para não puxar dependência nova
    # (email-validator) por uma checagem que o GoTrue refaz do lado dele.
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)
    nome: str = Field(min_length=1, max_length=255, description="Nome de quem recebe o login")


class ConvitePortalOut(BaseModel):
    id: UUID
    email: str
    criado_em: datetime
    # Nulo = convidado ainda não entrou. Preenche uma vez, no primeiro sinal
    # autenticado do login (ver app/routers/me.py) — e o trigger OC027 garante
    # que ninguém reescreve depois.
    aceito_em: Optional[datetime]
    convidado_por_nome: Optional[str]


@router.get("/{tomador_id}/portal/convites", response_model=List[ConvitePortalOut])
def get_convites_portal(
    tomador_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[ConvitePortalOut]:
    """A trilha de convites da empresa — quem recebeu janela, quando, e se entrou.

    Leitura aberta ao painel (o gate get_painel_user do main.py já barra
    tomador): operador precisa VER o estado do acesso para atender o cliente;
    o que é restrito a admin é CRIAR o acesso.
    """
    if db.query(Tomador.id).filter(Tomador.id == tomador_id).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")

    rows = db.execute(
        text("""
        select c.id, c.email, c.criado_em, c.aceito_em, u.nome as convidado_por_nome
          from convite_portal c
          -- Join por texto, não por cast: `convidado_por` é text (a migration
          -- 031 o define como rótulo de trilha, não FK), e um valor histórico
          -- fora do formato UUID explodiria o ::uuid da consulta inteira.
          left join usuario u on u.id::text = c.convidado_por
         where c.tomador_id = :t
         order by c.criado_em desc
        """),
        {"t": str(tomador_id)},
    ).all()
    return [
        ConvitePortalOut(
            id=r.id,
            email=r.email,
            criado_em=r.criado_em,
            aceito_em=r.aceito_em,
            convidado_por_nome=r.convidado_por_nome,
        )
        for r in rows
    ]


@router.post("/{tomador_id}/portal/convites", response_model=ConvitePortalOut, status_code=201)
def post_convidar_portal(
    tomador_id: UUID,
    body: ConvidarPortalIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> ConvitePortalOut:
    """Convida um e-mail para o portal do tomador. Admin only: dar a um CNPJ
    externo uma janela para os dados de crédito dele é ato de chave, como a
    autorização de município.

    A ORDEM DAS ESCRITAS importa e é deliberada:

    1. Supabase Auth PRIMEIRO — o id que ele devolve é o `sub` dos JWTs
       futuros, e a linha de `usuario` precisa nascer com ESTE id (senão o
       login autentica lá e morre em PERMISSAO_NEGADA aqui).
    2. `usuario` + `convite_portal` numa transação só, depois. Se ela falhar,
       sobra uma conta órfã no Auth — recuperável pelo painel do Supabase, e a
       mensagem de EmailJaRegistrado ensina o caminho. O inverso (linha local
       sem conta no Auth) seria pior: um login prometido que não autentica
       nunca, sem nada visível para limpar.

    `usuario_id` do convite nasce preenchido (o login já existe); `aceito_em`
    fica nulo até o primeiro sinal autenticado do convidado (app/routers/me.py).
    """
    if db.query(Tomador.id).filter(Tomador.id == tomador_id).one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")

    email = body.email.strip().lower()

    # Pré-checagem local: e-mail que já tem login (de QUALQUER papel) não pode
    # virar convite — o INSERT abaixo falharia depois de já ter criado a conta
    # no Auth, que é exatamente a órfã que a ordem das escritas tenta evitar.
    ja_existe = db.execute(
        text("select papel from usuario where lower(email) = :e"), {"e": email}
    ).first()
    if ja_existe is not None:
        raise HTTPException(
            status_code=409,
            detail=f"O e-mail {email} já tem login no sistema (papel {ja_existe.papel}).",
        )

    # Mesma origem em produção (o FastAPI serve o SPA); o override existe para
    # proxy que reescreve Host — ver o comentário de `public_url` no config.
    base = settings.public_url.strip() or str(request.base_url)
    redirect_to = f"{base.rstrip('/')}/definir-senha"

    try:
        auth_id = convidar_no_supabase(email, redirect_to)
    except ConvitesNaoConfigurados as exc:
        # 503 e não 500/422, pelo mesmo racional de storage_de_documentos
        # (app/routers/compliance.py): dependência indisponível, instrução
        # para quem opera a infraestrutura, nada gravado.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmailJaRegistrado as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ConviteFalhou as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    convite_id: UUID = uuid4()
    try:
        db.execute(
            text("""
            insert into usuario (id, email, nome, papel, ativo, tomador_id)
            values (:id, :email, :nome, 'tomador', true, :t)
            """),
            {"id": str(auth_id), "email": email, "nome": body.nome, "t": str(tomador_id)},
        )
        db.execute(
            text("""
            insert into convite_portal (id, tomador_id, email, convidado_por, usuario_id)
            values (:id, :t, :email, :por, :u)
            """),
            {
                "id": str(convite_id),
                "t": str(tomador_id),
                "email": email,
                "por": str(user.id),
                "u": str(auth_id),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A conta no Auth ficou órfã; a mensagem de EmailJaRegistrado (que um
        # novo convite para o mesmo e-mail vai disparar) ensina a removê-la.
        raise HTTPException(
            status_code=409,
            detail=f"Não foi possível criar o login para {email} — provavelmente um "
            "convite concorrente acabou de usá-lo. Recarregue a lista de convites.",
        ) from exc

    row = db.execute(
        text("select criado_em from convite_portal where id = :id"), {"id": str(convite_id)}
    ).one()
    return ConvitePortalOut(
        id=convite_id,
        email=email,
        criado_em=row.criado_em,
        aceito_em=None,
        convidado_por_nome=user.nome,  # type: ignore[arg-type]
    )
