"""
Fixtures pytest compartilhadas.

Requer Postgres real acessível via ORGCRED_TEST_DATABASE_URL (ou
ORGCRED_DATABASE_URL). Cada teste roda em uma transação revertida ao final
(isolamento sem custo de recriar o schema por teste), exceto os testes que
precisam de commits reais (concorrência, trigger em nova conexão) — esses
usam engines próprias.
"""

import os
import uuid
from pathlib import Path
from typing import Generator, Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def sqlstate_de(exc: BaseException) -> Optional[str]:
    """
    Extrai o SQLSTATE de uma exceção de driver, independente do driver.

    psycopg3 (em uso — ver pyproject.toml) expõe `.sqlstate`; psycopg2
    expunha `.pgcode`. Testes que provocam erro via SQL cru (fora de
    app.capital_engine, que já usa app.capital_engine._extrair_sqlstate)
    devem usar este helper em vez de acessar `.pgcode` direto — foi
    exatamente esse acesso direto que quebrou silenciosamente quando o
    projeto migrou de psycopg2 para psycopg3.
    """
    orig = getattr(exc, "orig", exc)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATIONS = [
    "001_initial_schema",
    "002_usuarios_papeis",
    "003_hardening_capital",
    "004_auditoria_autor",
    "005_ledger_imutavel",
    "006_novacao_e_inadimplencia",
    "007_agenda_de_parcelas",
    "008_aging_inadimplencia",
    "009_baixa_de_recebimento",
    "010_compliance_interno",
]


def _base_admin_url() -> str:
    """URL de conexão administrativa (banco 'postgres') para criar/dropar bancos de teste."""
    base = os.environ.get("ORGCRED_TEST_DATABASE_URL", os.environ.get("ORGCRED_DATABASE_URL", ""))
    if not base:
        pytest.skip("ORGCRED_TEST_DATABASE_URL/ORGCRED_DATABASE_URL não configurada")
    # Troca o nome do banco por 'postgres' para poder criar/dropar o banco de teste
    prefix = base.rsplit("/", 1)[0]
    return f"{prefix}/postgres"


@pytest.fixture(scope="session")
def test_db_name() -> str:
    """Nome único do banco de teste desta sessão pytest."""
    return f"orgcred_pytest_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def test_database_url(test_db_name: str) -> Generator[str, None, None]:
    """
    Cria um banco de teste isolado, aplica as migrations, e o remove ao final
    da sessão. Isolamento: cada execução de pytest usa um banco novo.
    """
    admin_url = _base_admin_url()
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{test_db_name}"'))

    db_url = f"{admin_url.rsplit('/', 1)[0]}/{test_db_name}"
    engine = create_engine(db_url)

    with engine.begin() as conn:
        for migration in MIGRATIONS:
            sql = (MIGRATIONS_DIR / f"{migration}.sql").read_text(encoding="utf-8")
            conn.execute(text(sql))

    engine.dispose()

    yield db_url

    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE)'))
    admin_engine.dispose()


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Generator[Engine, None, None]:
    """Engine SQLAlchemy apontando para o banco de teste."""
    eng = create_engine(test_database_url)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine: Engine) -> Generator[Session, None, None]:
    """
    Sessão de banco isolada por teste: cada teste roda dentro de uma
    transação externa revertida ao final. O código sob teste (capital_engine)
    chama session.commit()/rollback() normalmente — para que isso não encerre
    a transação externa, usamos o padrão SAVEPOINT (begin_nested) e o
    reabrimos automaticamente após cada commit/rollback do código testado.
    Ver: https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    session = SessionLocal()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture()
def tomador_autorizado(db_session: Session) -> uuid.UUID:
    """Cria um tomador no município autorizado; retorna seu id."""
    result = db_session.execute(
        text(
            """
            insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
            values (:cnpj, 'Padaria Teste ME', 'ME', 'Formoso', 'GO', true)
            returning id
            """
        ),
        {"cnpj": f"{uuid.uuid4().int % 10**14:014d}"},
    )
    db_session.commit()
    return result.scalar_one()


def baixar_parcelas(db_session: Session, operacao_id: uuid.UUID, numeros: list[int]) -> None:
    """Baixa parcelas via `fn_baixar_parcela`, criando um movimento por parcela.

    Existe porque, desde a migration 009, `update parcela set status='paga'`
    é recusado pelo banco (OC011) — não há caminho para dar uma parcela por
    paga sem lastro bancário, nem em teste. Cada baixa precisa do seu
    próprio movimento: o índice único impede que um crédito baixe duas.
    """
    for numero in numeros:
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = :n"),
            {"op": str(operacao_id), "n": numero},
        ).one()
        movimento_id = db_session.execute(
            text("""
            insert into movimento_bancario (data_movimento, valor, documento)
            values (current_date, :valor, :doc) returning id
            """),
            {"valor": parcela.valor_total, "doc": f"DOC-{uuid.uuid4().hex[:12]}"},
        ).scalar_one()
        db_session.execute(
            text("select fn_baixar_parcela(:p, :m)"),
            {"p": str(parcela.id), "m": str(movimento_id)},
        )
    db_session.commit()


@pytest.fixture()
def capital_constituido(db_session: Session) -> None:
    """Constitui capital social de R$ 50.000 para os testes."""
    db_session.execute(
        text("insert into esc_capital_social (valor, tipo_evento) values (50000, 'constituicao')")
    )
    db_session.commit()
