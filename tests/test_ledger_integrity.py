"""
Testes da integridade do capital_ledger (migration 005, Fase 7):
proteção append-only e verificação da cadeia de hash.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.ledger_integrity import verificar_integridade_ledger
from tests.conftest import sqlstate_de


def _criar_operacao(db_session: Session, tomador_id: uuid.UUID, valor: int) -> uuid.UUID:
    result = db_session.execute(
        text(
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values
                (:tomador_id, 'emprestimo', :valor, 2.5, 'PRICE', 12, 'registrada', 'REG-TEST')
            returning id
            """
        ),
        {"tomador_id": str(tomador_id), "valor": valor},
    )
    db_session.commit()
    return result.scalar_one()


class TestProtecaoAppendOnly:
    def test_bloqueia_update_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(
                text("update capital_ledger set valor = 999999 where operacao_id = :id"),
                {"id": str(op_id)},
            )
            db_session.commit()

        db_session.rollback()
        assert sqlstate_de(exc_info.value) == "OC007"

    def test_bloqueia_delete_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(
                text("delete from capital_ledger where operacao_id = :id"), {"id": str(op_id)}
            )
            db_session.commit()

        db_session.rollback()
        assert sqlstate_de(exc_info.value) == "OC007"


class TestCadeiaDeHash:
    def test_cadeia_integra_apos_operacoes_normais(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        quebras = verificar_integridade_ledger(db_session)

        assert quebras == []

    def test_cada_linha_tem_hash_preenchido(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        row = db_session.execute(
            text("select prev_hash, current_hash from capital_ledger where operacao_id = :id"),
            {"id": str(op_id)},
        ).one()

        assert row.current_hash is not None
        assert len(row.current_hash) == 64  # sha256 em hex

    def test_detecta_adulteracao_via_bypass_do_trigger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """
        A proteção append-only (OC007) impede UPDATE/DELETE via caminho
        normal. Este teste simula o cenário que a cadeia de hash existe
        PARA cobrir: alguém com privilégio de superusuário desabilitando o
        trigger temporariamente para adulterar uma linha, depois
        reabilitando — a cadeia detecta isso mesmo que o append-only não
        tenha impedido.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        db_session.execute(
            text("alter table capital_ledger disable trigger trg_bloquear_update_ledger")
        )
        db_session.execute(
            text("update capital_ledger set valor = 999999 where operacao_id = :id"),
            {"id": str(op_id)},
        )
        db_session.execute(
            text("alter table capital_ledger enable trigger trg_bloquear_update_ledger")
        )
        db_session.commit()

        quebras = verificar_integridade_ledger(db_session)

        assert len(quebras) == 1
        assert quebras[0].ledger_id is not None
