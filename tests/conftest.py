"""
Fixtures pytest compartilhadas.

Requer Postgres real acessível via ORGCRED_TEST_DATABASE_URL (ou
ORGCRED_DATABASE_URL). Cada teste roda em uma transação revertida ao final
(isolamento sem custo de recriar o schema por teste), exceto os testes que
precisam de commits reais (concorrência, trigger em nova conexão) — esses
usam engines próprias.
"""

import hashlib
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
    "011_apuracao_fiscal",
    "012_contrato_e_registro",
    "013_gate_registro_confirmado",
    "014_gate_identificacao",
]


def _url_configurada() -> str:
    """URL do Postgres de teste, ou string vazia se nenhuma variável estiver setada."""
    return os.environ.get("ORGCRED_TEST_DATABASE_URL", os.environ.get("ORGCRED_DATABASE_URL", ""))


def pytest_configure(config: pytest.Config) -> None:
    """Recusa a suíte-fantasma: sem banco, em CI, o pytest não roda.

    Todo teste de invariante depende de `db_session`. Sem URL de banco os
    ~200 viram skip e o pytest sai 0 (reproduzido em 2026-08-12). Em CI esse
    zero é a única coisa que autoriza um deploy, e estaria dizendo "o schema
    está provado" sobre uma execução que não abriu conexão nenhuma. Aqui
    isso vira erro de uso, antes da coleta.

    Fora da CI o skip continua — quem não tem Postgres local ainda consegue
    rodar os testes que não dependem de banco. Mas então o --cov-fail-under
    do pyproject.toml estaria medindo a cobertura de uma suíte que não rodou
    (dois terços do total, contra os ~92% da execução real) e reprovaria por
    um motivo falso; nesse caso, e só nesse, ele é desligado.
    """
    if _url_configurada():
        return

    if os.environ.get("CI"):
        raise pytest.UsageError(
            "CI detectada e ORGCRED_TEST_DATABASE_URL/ORGCRED_DATABASE_URL ausente. "
            "Sem Postgres os testes de invariante (triggers PL/pgSQL, SQLSTATEs da "
            "classe OC) viram skip e a suíte sai 0 sem provar nada — recusando rodar."
        )

    # Os dois namespaces, de propósito: o pytest-cov guarda `options =
    # early_config.known_args_namespace` (plugin.py, pytest_cmdline_main), que
    # é uma CÓPIA feita antes de `config.option` ser preenchido. Zerar só
    # `config.option` não tem efeito nenhum — o piso continuava reprovando.
    for namespace in (config.option, getattr(config, "known_args_namespace", None)):
        if getattr(namespace, "cov_fail_under", None):
            namespace.cov_fail_under = 0


def _base_admin_url() -> str:
    """URL de conexão administrativa (banco 'postgres') para criar/dropar bancos de teste."""
    base = _url_configurada()
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


def _inserir_tomador(db_session: Session, razao_social: str, autorizado: bool = True) -> uuid.UUID:
    result = db_session.execute(
        text(
            """
            insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
            values (:cnpj, :razao, 'ME', 'Formoso', 'GO', :autorizado)
            returning id
            """
        ),
        {
            "cnpj": f"{uuid.uuid4().int % 10**14:014d}",
            "razao": razao_social,
            "autorizado": autorizado,
        },
    )
    db_session.commit()
    return result.scalar_one()


@pytest.fixture()
def tomador_autorizado(db_session: Session) -> uuid.UUID:
    """Tomador no município autorizado E com identificação arquivada.

    A identificação entra aqui porque, desde a migration 014, ativar exige
    evidência arquivada (Lei 9.613/98, art. 10, I) — um tomador sem ela não
    representa o caso comum, representa o caso bloqueado. Para testar o
    bloqueio existe `tomador_sem_identificacao`.
    """
    tomador_id = _inserir_tomador(db_session, "Padaria Teste ME")
    arquivar_identificacao(db_session, tomador_id)
    return tomador_id


@pytest.fixture()
def tomador_sem_identificacao(db_session: Session) -> uuid.UUID:
    """Tomador no município autorizado e SEM nenhuma evidência arquivada —
    o cenário que a migration 014 passou a recusar."""
    return _inserir_tomador(db_session, "Mercearia Sem Papel ME")


def confirmar_registro(
    db_session: Session, operacao_id: uuid.UUID, entidade: str = "CRDC"
) -> uuid.UUID:
    """Cria e confirma o registro em entidade registradora.

    Desde a migration 013, ativar exige registro CONFIRMADO — o gate do
    Art. 5º §3º deixou de aceitar texto livre. Todo teste que ativa uma
    operação passa por aqui, o que também significa que o gate é exercido
    dezenas de vezes por execução da suíte.
    """
    registro_id = db_session.execute(
        text("""
        insert into registro_operacao (operacao_id, entidade, status, protocolo, confirmado_em)
        values (:o, :e, 'confirmado', :p, clock_timestamp())
        returning id
        """),
        {"o": str(operacao_id), "e": entidade, "p": f"PROTO-{uuid.uuid4().hex[:10]}"},
    ).scalar_one()
    db_session.commit()
    return registro_id


def arquivar_identificacao(
    db_session: Session, tomador_id: uuid.UUID, tipo: str = "contrato_social"
) -> uuid.UUID:
    """Arquiva uma evidência de identificação para o tomador.

    Desde a migration 014, ativar exige que o tomador tenha ao menos uma
    evidência arquivada (Lei 9.613/98, art. 10, I). O hash é arbitrário aqui
    — o que o gate verifica é a EXISTÊNCIA da evidência; a conferência de
    conteúdo é assunto de `POST /compliance/documentos/{id}/verificar`.
    """
    documento_id = db_session.execute(
        text("""
        insert into tomador_documento
            (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
        values (:t, :tipo, :nome, :sha, current_date + interval '5 years')
        returning id
        """),
        {
            "t": str(tomador_id),
            "tipo": tipo,
            "nome": f"{tipo}.pdf",
            "sha": hashlib.sha256(f"{tomador_id}:{tipo}".encode()).hexdigest(),
        },
    ).scalar_one()
    db_session.commit()
    return documento_id


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
