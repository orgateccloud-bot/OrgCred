"""Guarda de sincronia entre as três fontes de verdade do schema.

O schema do OrgCred é descrito em três lugares que precisam concordar:

1. `migrations/NNN_nome.sql` — o SQL de verdade, onde vivem os invariantes
   legais (triggers PL/pgSQL, SQLSTATEs da classe OC);
2. `alembic/versions/NNNN_nome.py` — a revisão que aplica esse SQL em
   produção, lendo o próprio arquivo via `op.execute` (ver o ADR em
   `alembic/README_MIGRACAO.md`);
3. a lista `MIGRATIONS` em `tests/conftest.py` — a ordem em que o banco de
   teste é construído a cada sessão pytest.

Nada obrigava as três a andarem juntas. Uma migration nova aplicada só pelo
alembic passa a valer em produção sem NUNCA ser exercitada por um teste, e a
suíte segue verde provando o schema antigo — uma CI que autoriza deploy sem
ter visto o que vai subir. Este módulo é essa obrigação.

Não toca no banco de propósito: é leitura de diretório. Roda sem Postgres, o
que também o torna o único teste desta suíte que continua provando algo
quando `ORGCRED_TEST_DATABASE_URL` não está configurada.
"""

import re
from pathlib import Path

from tests.conftest import MIGRATIONS, MIGRATIONS_DIR


ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"

# 001_initial_schema.sql -> ("001", "initial_schema")
_SQL_RE = re.compile(r"^(\d{3})_(.+)$")
# 0001_initial_schema.py -> ("0001", "initial_schema")
_REVISAO_RE = re.compile(r"^(\d{4})_(.+)$")


def _sql_no_disco() -> list[str]:
    """Stems dos arquivos SQL, em ordem de aplicação (a numeração é a ordem)."""
    return sorted(caminho.stem for caminho in MIGRATIONS_DIR.glob("*.sql"))


def _revisoes_no_disco() -> list[str]:
    """Stems das revisões alembic, ignorando `__init__.py` se algum dia existir."""
    return sorted(
        caminho.stem
        for caminho in ALEMBIC_VERSIONS_DIR.glob("*.py")
        if not caminho.name.startswith("__")
    )


class TestConftestVersusSQL:
    """A lista MIGRATIONS do conftest tem que ser o diretório inteiro."""

    def test_lista_cobre_todos_os_arquivos_sql(self) -> None:
        no_disco = set(_sql_no_disco())
        na_lista = set(MIGRATIONS)

        nao_exercitadas = sorted(no_disco - na_lista)
        assert not nao_exercitadas, (
            f"migrations/ tem {nao_exercitadas} que a lista MIGRATIONS de tests/conftest.py "
            "não aplica — o banco de teste é construído sem elas e a suíte inteira prova "
            "um schema que não é o que vai para produção."
        )

        inexistentes = sorted(na_lista - no_disco)
        assert not inexistentes, (
            f"MIGRATIONS de tests/conftest.py cita {inexistentes}, que não existe em "
            "migrations/ — a criação do banco de teste vai quebrar com FileNotFoundError."
        )

    def test_lista_esta_na_ordem_de_aplicacao(self) -> None:
        """A ordem não é cosmética: a 013 recria o gate que a 006 instalou.

        Aplicar fora de ordem não dá erro de sintaxe — dá um schema com o
        gate errado, silenciosamente.
        """
        assert MIGRATIONS == _sql_no_disco(), (
            "MIGRATIONS de tests/conftest.py está fora da ordem numérica; cada migration "
            "assume o estado deixada pela anterior."
        )

    def test_numeracao_dos_sql_e_contigua(self) -> None:
        """Um buraco na numeração é uma migration que sumiu do repositório."""
        numeros = []
        for stem in _sql_no_disco():
            casado = _SQL_RE.match(stem)
            assert casado, f"migrations/{stem}.sql não segue o padrão NNN_nome"
            numeros.append(int(casado.group(1)))

        assert numeros == list(
            range(1, len(numeros) + 1)
        ), f"numeração de migrations/ não é contígua a partir de 001: {numeros}"


class TestAlembicVersusSQL:
    """Cada SQL precisa ter uma revisão alembic que o aplique em produção."""

    def test_contagem_bate_com_os_arquivos_sql(self) -> None:
        sql = _sql_no_disco()
        revisoes = _revisoes_no_disco()

        assert len(revisoes) == len(sql), (
            f"{len(sql)} arquivos em migrations/ e {len(revisoes)} revisões em "
            "alembic/versions/. O que só existe no SQL nunca sobe em produção "
            "(`alembic upgrade head` não o conhece); o que só existe no alembic "
            "sobe sem nenhum teste ter visto."
        )

    def test_cada_sql_tem_revisao_correspondente(self) -> None:
        """A correspondência é pelo nome: NNN_nome.sql <-> 0NNN_nome.py."""
        nomes_sql = set()
        for stem in _sql_no_disco():
            casado = _SQL_RE.match(stem)
            assert casado
            nomes_sql.add(casado.group(2))

        nomes_revisao = set()
        for stem in _revisoes_no_disco():
            casado = _REVISAO_RE.match(stem)
            assert casado, f"alembic/versions/{stem}.py não segue o padrão NNNN_nome"
            nomes_revisao.add(casado.group(2))

        assert nomes_sql == nomes_revisao, (
            "migrations/ e alembic/versions/ divergem: "
            f"só no SQL={sorted(nomes_sql - nomes_revisao)}, "
            f"só no alembic={sorted(nomes_revisao - nomes_sql)}"
        )

    def test_cada_revisao_executa_o_proprio_sql(self) -> None:
        """O `upgrade()` da revisão 0NNN tem que abrir o arquivo NNN.

        As revisões não redigitam o schema: leem o .sql e dão `op.execute`.
        Um copy-paste que esqueceu de trocar o nome do arquivo reaplica a
        migration anterior e passa despercebido — o upgrade não falha, só
        não faz nada do que promete.

        A busca é pelo literal entre aspas e só dentro do corpo de
        `upgrade()` — de `def upgrade` até `def downgrade`. As duas bordas
        importam: o docstring do módulo também cita o arquivo (`Baseline
        convertido de migrations/014_...sql`) e não prova nada — bastaria
        alguém escrevê-lo entre aspas para mascarar um upgrade errado; e o
        downgrade referencia SQL antigo legitimamente (a 0014 volta para a
        013, a 0006 volta para 003 e 004).
        """
        for stem in _revisoes_no_disco():
            casado = _REVISAO_RE.match(stem)
            assert casado
            sql_esperado = f"{casado.group(1)[1:]}_{casado.group(2)}.sql"
            corpo = (ALEMBIC_VERSIONS_DIR / f"{stem}.py").read_text(encoding="utf-8")
            upgrade = corpo.split("def upgrade", 1)[-1].split("def downgrade", 1)[0]
            assert f'"{sql_esperado}"' in upgrade, (
                f"o upgrade() de alembic/versions/{stem}.py não abre "
                f"migrations/{sql_esperado} — essa revisão está aplicando o SQL de outra "
                "migration, ou o schema de produção deixou de vir do arquivo versionado."
            )
