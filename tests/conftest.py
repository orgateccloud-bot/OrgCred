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
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATIONS = [
    "001_initial_schema",
    "002_usuarios_papeis",
    "003_hardening_capital",
    "004_auditoria_autor",
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


@pytest.fixture()
def capital_constituido(db_session: Session) -> None:
    """Constitui capital social de R$ 50.000 para os testes."""
    db_session.execute(
        text("insert into esc_capital_social (valor, tipo_evento) values (50000, 'constituicao')")
    )
    db_session.commit()
