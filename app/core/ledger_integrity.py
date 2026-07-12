"""
Verificação de integridade do capital_ledger (hash-chain, migration 005).

Uso recomendado: rotina periódica (ex. diária, junto do backup) que chama
verificar_integridade_ledger() e alerta se houver quebras — a cadeia por si
só não previne adulteração com acesso direto ao banco, só a torna
detectável.
"""

from dataclasses import dataclass
from typing import List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class QuebraIntegridade:
    ledger_id: UUID
    motivo: str


def verificar_integridade_ledger(db: Session) -> List[QuebraIntegridade]:
    """
    Retorna a lista de linhas do ledger cuja cadeia de hash não bate —
    lista vazia significa cadeia íntegra. Delega o recálculo ao Postgres
    (fn_verificar_cadeia_ledger, migration 005) para evitar duas
    implementações do algoritmo de hash divergindo com o tempo.
    """
    rows = db.execute(text("select id, motivo from fn_verificar_cadeia_ledger()")).all()
    return [QuebraIntegridade(ledger_id=row.id, motivo=row.motivo) for row in rows]
