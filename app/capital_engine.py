"""
Camada de serviço para o ciclo de vida de uma operação de crédito.

Princípio: a API executa a transição de status e DEIXA O BANCO decidir.
Os triggers (migrations 001+003) são a fonte única de verdade sobre:
teto de capital, gate geográfico, máquina de estados e exigência de
registro na entidade registradora.

Identificação de erro por SQLSTATE (classe 'OC'), não por substring da
mensagem — a revisão de 2026-07-11 apontou que matching por texto quebra
silenciosamente se a mensagem do trigger mudar. Códigos:
  OC001 teto de capital excedido
  OC002 tomador fora da área de atuação
  OC003 transição de status inválida
  OC004 ativação sem registro na entidade registradora
  OC005 redução de capital abaixo do comprometido
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    MunicipioNaoAutorizado,
    OperacaoNaoEncontrada,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    TetoCapitalExcedido,
    TransicaoInvalida,
)
from app.core.metrics import registrar_ativacao
from app.models import OperacaoCredito


_PGCODE_MAP = {
    "OC001": TetoCapitalExcedido,
    "OC002": MunicipioNaoAutorizado,
    "OC003": TransicaoInvalida,
    "OC004": RegistroEntidadeAusente,
    "OC005": ReducaoCapitalBloqueada,
}


def _traduz_erro_banco(exc: DBAPIError) -> Exception:
    pgcode: Optional[str] = getattr(getattr(exc, "orig", None), "pgcode", None)
    exc_cls = _PGCODE_MAP.get(pgcode) if pgcode else None
    msg = str(getattr(exc, "orig", exc)).splitlines()[0]
    if exc_cls:
        return exc_cls(msg)
    return exc


def consultar_capital_disponivel(db: Session) -> Decimal:
    """Leitura informativa para UX — a validação real é o trigger.

    Nota de revisão: entre esta leitura e a ativação, outra transação
    pode consumir o capital exibido. O advisory lock garante que o teto
    nunca é violado, mas NÃO garante que o valor mostrado ao usuário
    ainda estará disponível ao clicar. A UI deve tratar OC001 como
    resultado normal, não como erro inesperado.
    """
    row = db.execute(
        text("""
        select (select capital_atual from v_capital_atual)
             - coalesce((select sum(valor_principal) from operacao_credito
                         where status = 'ativa'), 0) as disponivel
    """)
    ).first()
    if row is None:
        return Decimal("0")
    return Decimal(row.disponivel)


def ativar_operacao(
    db: Session, operacao_id: UUID, usuario_id: Optional[str] = None
) -> OperacaoCredito:
    """
    Tenta 'registrada' -> 'ativa'; o banco valida tudo que importa.

    `usuario_id` (tipicamente CurrentUser.user_id do JWT autenticado, ver
    app/core/auth.py) é propagado ao trigger via `SET LOCAL app.user_id`,
    válido só nesta transação — a migration 004 usa
    `current_setting('app.user_id', true)` para registrar o autor no
    capital_ledger. Sem isso, a trilha de auditoria segue funcionando, só
    sem autor (equivalente ao comportamento antes da Fase 6).

    Sempre executa o SET LOCAL (com o valor ou com DEFAULT) para não
    depender do estado anterior da conexão física: como as conexões vêm de
    um pool, uma sessão sem usuario_id poderia herdar o valor setado por uma
    ativação anterior na mesma conexão se o guard fosse condicional.
    """
    if usuario_id:
        db.execute(text("SET LOCAL app.user_id = :usuario_id"), {"usuario_id": usuario_id})
    else:
        db.execute(text("SET LOCAL app.user_id TO DEFAULT"))

    op: Optional[OperacaoCredito] = (
        db.query(OperacaoCredito).filter(OperacaoCredito.id == operacao_id).one_or_none()
    )
    if op is None:
        raise OperacaoNaoEncontrada(f"Operação {operacao_id} não existe.")

    op.status = "ativa"  # type: ignore[assignment]
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    db.refresh(op)
    registrar_ativacao()
    return op
