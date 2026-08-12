"""
Testes da integridade do capital_ledger (migration 005, Fase 7):
proteção append-only e verificação da cadeia de hash.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.ledger_integrity import verificar_integridade_ledger
from tests.conftest import confirmar_registro, sqlstate_de


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
    op_id = result.scalar_one()
    confirmar_registro(db_session, op_id)
    return op_id


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

    def test_bloqueia_truncate_no_ledger(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """O furo que a migration 016 fechou.

        As guardas da 005 são BEFORE UPDATE/DELETE FOR EACH ROW, e TRUNCATE
        não visita linhas: `truncate table capital_ledger` apagava a cadeia
        de hash inteira sem levantar erro nenhum — a prova documental do teto
        do Art. 5º sumia com um comando de sete palavras, e o
        `fn_verificar_cadeia_ledger()` passava a devolver 0 linhas (íntegro)
        sobre um ledger vazio. A 016 instalou o BEFORE TRUNCATE de statement,
        que é a única forma de alcançar TRUNCATE de dentro do banco.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)

        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(text("truncate table capital_ledger"))
            db_session.commit()

        db_session.rollback()
        assert sqlstate_de(exc_info.value) == "OC007"

        assert (
            db_session.execute(
                text("select count(*) from capital_ledger where operacao_id = :id"),
                {"id": str(op_id)},
            ).scalar_one()
            == 1
        )

    def test_bloqueia_truncate_no_capital_social(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        """Mesma trava na tabela que DEFINE o teto.

        A 015 documentou que fechar o TRUNCATE do capital_ledger e o do
        esc_capital_social é uma decisão só — fechar um e deixar o outro daria
        a impressão falsa de cobertura, e o do capital social é o mais barato
        dos dois: zerá-lo derruba o teto do Art. 5º para 0 com operações
        comprometidas, sem passar pelo OC005.
        """
        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(text("truncate table esc_capital_social"))
            db_session.commit()

        db_session.rollback()
        assert sqlstate_de(exc_info.value) == "OC021"

        assert db_session.execute(
            text("select capital_atual from v_capital_atual")
        ).scalar_one() == Decimal("50000.00")

    def test_bloqueia_truncate_no_evento_de_operacao(
        self, db_session: Session, tomador_autorizado: uuid.UUID, capital_constituido: None
    ) -> None:
        """A quinta trilha, e a que quase ficou de fora.

        `operacao_evento` é a única outra tabela que o schema declara
        "append-only" com todas as letras (008: "append-only, como o
        capital_ledger"), e a guarda dela tem exatamente a mesma forma —
        BEFORE UPDATE/DELETE FOR EACH ROW, OC010 — que TRUNCATE atravessa
        pelo mesmo motivo. `delete from operacao_evento` é recusado; sem esta
        trava, `truncate table operacao_evento` apagava o mesmo conteúdo sem
        erro nenhum.

        O que se perde é diferente do ledger, e por isso importa: o ledger
        prova QUANTO capital está comprometido, esta trilha prova QUEM fez
        cada ato e QUANDO. Apagá-la deixa as operações no estado atual sem
        registro de como chegaram nele — e o ledger protegido ao lado dá a
        impressão de que a auditoria continua inteira.
        """
        op_id = _criar_operacao(db_session, tomador_autorizado, 30_000)
        ativar_operacao(db_session, op_id)
        antes = db_session.execute(
            text("select count(*) from operacao_evento where operacao_id = :id"),
            {"id": str(op_id)},
        ).scalar_one()
        assert antes > 0, "a ativação tinha que ter gravado evento — o teste provaria o vazio."

        with pytest.raises(DBAPIError) as exc_info:
            db_session.execute(text("truncate table operacao_evento"))
            db_session.commit()

        db_session.rollback()
        assert sqlstate_de(exc_info.value) == "OC010"

        assert (
            db_session.execute(
                text("select count(*) from operacao_evento where operacao_id = :id"),
                {"id": str(op_id)},
            ).scalar_one()
            == antes
        )

    def test_truncate_segue_livre_fora_das_trilhas(self, db_session: Session) -> None:
        """Caminho feliz: a 016 não proibiu TRUNCATE, proibiu TRUNCATE NAS
        TRILHAS. `movimento_bancario` é imutável linha a linha (OC012) mas não
        é trilha append-only de conformidade — limpar a importação de um
        extrato inteiro continua sendo operação administrativa legítima.

        O `cascade` não é enfeite e não é opcional: o Postgres recusa TRUNCATE
        em tabela referenciada por FK (aqui, `parcela.movimento_id`) mesmo
        quando a referenciadora está vazia. Ou seja, este comando alcança
        `parcela` junto — o que confirma o limite declarado no topo da 016:
        as travas novas valem para as CINCO trilhas, e não transformam
        TRUNCATE numa operação segura em geral. Quem limpa extrato em base com
        agenda emitida está apagando a agenda também."""
        db_session.execute(
            text("""
            insert into movimento_bancario (data_movimento, valor, documento)
            values (current_date, 1000, 'FITID-TRUNCATE')
            """)
        )
        db_session.execute(text("truncate table movimento_bancario cascade"))

        assert db_session.execute(text("select count(*) from movimento_bancario")).scalar_one() == 0
        db_session.rollback()


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
