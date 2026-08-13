"""Router: trilha de auditoria do capital_ledger (hash-chain, migration 005)."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/auditoria", tags=["auditoria"])

# O ledger é append-only e cresce para sempre: uma linha por ativação, baixa,
# novação e movimento de capital, sem nenhum expurgo possível (a migration 005
# bloqueia UPDATE/DELETE e a 016 bloqueia TRUNCATE — é assim de propósito, é a
# prova documental do teto do Art. 5º). Sem página, este endpoint devolvia a
# tabela inteira a cada abertura da tela de auditoria e a cada polling do
# dashboard; num ano de operação isso é um JSON de dezenas de MB montado
# inteiro em memória, no servidor e no navegador.
#
# 100 é o padrão porque é o que o painel consegue exibir e usar: a tela de
# auditoria lista eventos recentes e o card de evolução de saldo plota os
# últimos pontos. 500 é o teto porque acima disso o custo de serialização já
# supera o de uma segunda requisição.
TAMANHO_PAGINA_PADRAO = 100
TAMANHO_PAGINA_MAX = 500

# Teto do NÚMERO da página, e não só do tamanho dela. `pagina` entrava com
# piso (`ge=1`, para não virar OFFSET negativo) e sem teto: como o Pydantic
# aceita inteiro de precisão arbitrária, `?pagina=10000000000000000000` virava
# um OFFSET maior que o bigint do Postgres, o driver estourava e o endpoint
# respondia 500 — um 500 que qualquer usuário autenticado dispara de propósito
# só mudando a query string, poluindo log e métrica de erro. Com o teto o
# mesmo pedido vira 422, que é o que ele sempre foi: parâmetro inválido.
#
# 1.000.000 de páginas × 500 eventos = 500 milhões de eventos endereçáveis,
# ordens de grandeza acima de qualquer ledger real desta ESC, e o maior
# deslocamento possível (5×10⁸) cabe folgado no bigint.
PAGINA_MAX = 1_000_000


class LedgerEventoOut(BaseModel):
    id: UUID
    evento_tipo: str
    valor: Decimal
    operacao_id: Optional[UUID]
    saldo_disponivel_pos: Decimal
    usuario_nome: Optional[str]
    created_at: datetime
    prev_hash: Optional[str]
    current_hash: Optional[str]


class QuebraCadeia(BaseModel):
    id: UUID
    motivo: str


class AuditoriaOut(BaseModel):
    integro: bool
    quebras: List[QuebraCadeia]
    eventos: List[LedgerEventoOut]
    # Campos ADITIVOS (passo 14): `integro`, `quebras` e `eventos` continuam
    # com o mesmo nome e o mesmo formato, então o painel atual segue lendo o
    # que sempre leu. O que mudou é que `eventos` agora traz uma página, e não
    # a tabela toda — daí `total` existir: sem ele o cliente não teria como
    # distinguir "são só estes" de "há mais lá atrás".
    total: int
    pagina: int
    tamanho_pagina: int


@router.get("", response_model=AuditoriaOut)
def get_auditoria(
    pagina: int = Query(
        1,
        ge=1,
        le=PAGINA_MAX,
        description="Página (1-based), ordenada do mais recente",
    ),
    tamanho: int = Query(
        TAMANHO_PAGINA_PADRAO,
        ge=1,
        le=TAMANHO_PAGINA_MAX,
        description=f"Eventos por página (máximo {TAMANHO_PAGINA_MAX})",
    ),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AuditoriaOut:
    """
    Trilha de auditoria em duas camadas: eventos legíveis (com nome do
    usuário quando disponível) e o resultado da verificação da cadeia de
    hash (`fn_verificar_cadeia_ledger()`, migration 005) — 0 quebras
    significa cadeia íntegra.

    `eventos` é paginado; `quebras` NÃO é, de propósito. A verificação da
    cadeia é uma afirmação sobre o ledger inteiro: paginar as quebras faria
    `integro` significar "esta página está íntegra", que é exatamente a
    mentira que a cadeia de hash existe para impedir. Na operação normal a
    lista vem vazia; se vier grande, o tamanho dela é a notícia.
    """
    quebras_rows = db.execute(text("select id, motivo from fn_verificar_cadeia_ledger()")).all()
    quebras = [QuebraCadeia(id=row.id, motivo=row.motivo) for row in quebras_rows]

    total = db.execute(text("select count(*) from capital_ledger")).scalar_one()

    eventos_rows = db.execute(
        text("""
        select
            l.id, l.evento_tipo, l.valor, l.operacao_id, l.saldo_disponivel_pos,
            u.nome as usuario_nome, l.created_at, l.prev_hash, l.current_hash
        from capital_ledger l
        left join usuario u on u.id::text = l.usuario_id
        order by l.created_at desc, l.id desc
        limit :limite offset :deslocamento
    """),
        {"limite": tamanho, "deslocamento": (pagina - 1) * tamanho},
    ).all()
    eventos = [
        LedgerEventoOut(
            id=row.id,
            evento_tipo=row.evento_tipo,
            valor=row.valor,
            operacao_id=row.operacao_id,
            saldo_disponivel_pos=row.saldo_disponivel_pos,
            usuario_nome=row.usuario_nome,
            created_at=row.created_at,
            prev_hash=row.prev_hash,
            current_hash=row.current_hash,
        )
        for row in eventos_rows
    ]

    return AuditoriaOut(
        integro=len(quebras) == 0,
        quebras=quebras,
        eventos=eventos,
        total=int(total),
        pagina=pagina,
        tamanho_pagina=tamanho,
    )
