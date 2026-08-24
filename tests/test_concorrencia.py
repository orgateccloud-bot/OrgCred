"""
Provas de concorrência do motor de capital.

O que este arquivo prova é o único invariante que um teste sequencial não
alcança: sob duas transações simultâneas, o teto do Art. 5º da LC 167/2019
continua valendo. O ataque original (F1, revisão de 2026-07-11) era duas
ativações de 30.000 contra um capital de 50.000 — cada uma cabia sozinha, e
sem serialização as duas passavam, deixando 60.000 emprestados. A defesa é
o `pg_advisory_xact_lock(hashtext('orgcred_capital_gate'))` que todo caminho
de movimentação de capital toma antes de ler o comprometido.

HISTÓRICO DESTE ARQUIVO (por que ele foi reescrito):
A versão anterior era um script standalone que aplicava SOMENTE as migrations
001, 002 e 003 e falava psycopg2. As duas coisas o tinham esvaziado:

- `fn_check_teto_capital` foi redefinida por 003, 004, 006, 013 e 014 (o
  PL/pgSQL não tem substituição parcial: cada migration recopia a função
  inteira). Parando na 003, o teste exercitava um trigger que não existe mais
  em lugar nenhum — sem o comprometido de 'inadimplente' (006), sem o gate de
  registro confirmado (013), sem o gate de identificação (014). Passava
  provando um motor de 2026-07-11.
- o projeto fala psycopg3 desde a migração de driver; psycopg2 não está nas
  dependências. Só o job `integration` do CircleCI o instalava à parte, e o
  `--ignore=tests/test_concorrencia.py` no addopts do pyproject.toml
  garantia que a suíte pytest NUNCA rodasse este arquivo. A prova de
  concorrência estava fora de todo caminho que alguém olha.

Agora é um módulo pytest normal: aplica as 14 migrations reaproveitando a
lista `MIGRATIONS` do conftest (a mesma que o resto da suíte usa, então a
divergência que criou este problema não pode voltar), fala psycopg3 pela
mesma engine SQLAlchemy do projeto e afirma por SQLSTATE.

SOBRE FLAKINESS: nenhum `sleep`. A sincronização é uma `threading.Barrier`,
e a conexão de cada thread é aberta ANTES da barreira — se o handshake TCP
ficasse do outro lado dela, uma thread chegaria ao UPDATE dezenas de
milissegundos depois da outra e a corrida deixaria de existir sem que
ninguém percebesse (o teste seguiria verde). Quem ganha o advisory lock é
indeterminado de propósito; as asserções cobrem AS DUAS ordens e recusam
qualquer terceiro desfecho. As corridas rodam num banco só delas, zerado
entre uma e outra — os dados aqui são commitados de verdade (é o ponto), e
num banco compartilhado vazariam para os testes que rodam em transação
revertida, mexendo no capital que eles enxergam.
"""

import threading
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, Generator, Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import (
    MIGRATIONS,
    MIGRATIONS_DIR,
    _base_admin_url,
    arquivar_identificacao,
    confirmar_registro,
    quitar_operacao,
    sqlstate_de,
)


# Redes de segurança contra travamento, não temporizadores da corrida: a
# disputa pelo advisory lock resolve em milissegundos. Se algum destes
# estourar, houve deadlock ou lock não liberado — e é melhor o teste falhar
# com mensagem do que a suíte inteira pendurar.
TIMEOUT_BARREIRA_S = 30.0
TIMEOUT_THREAD_S = 60.0
TIMEOUT_STATEMENT_MS = 30_000


# ---------------------------------------------------------------------
# Infraestrutura: um banco só para as corridas, zerado entre elas
# ---------------------------------------------------------------------
# A fixture `db_session` do conftest não serve aqui: ela roda o teste dentro
# de uma transação revertida no fim, e concorrência exige commit real em
# conexões distintas. Daí o banco próprio.
#
# Um banco por corrida seria mais óbvio, mas cada `create database` novo
# custa conexões novas, e conexão é o recurso caro deste arquivo: o pool é
# reaproveitado entre as quatro corridas, e o estado volta ao zero por
# TRUNCATE. As migrations também são aplicadas uma única vez.


def _url_do_banco(admin_url: str, nome: str) -> str:
    return f"{admin_url.rsplit('/', 1)[0]}/{nome}"


@pytest.fixture(scope="module")
def admin_engine() -> Generator[Engine, None, None]:
    """Conexão administrativa (banco 'postgres'), de onde se cria e dropa."""
    engine = create_engine(_base_admin_url(), isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def engine_conc(admin_engine: Engine) -> Generator[Engine, None, None]:
    """Banco das corridas, com as 14 migrations aplicadas.

    A lista vem de `tests.conftest.MIGRATIONS` de propósito: era a divergência
    entre a lista daqui e a de lá que deixava este arquivo provando um schema
    de três migrations atrás. Não há segunda lista para desatualizar.
    """
    admin_url = _base_admin_url()
    nome = f"orgcred_conc_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect() as conn:
        conn.execute(text(f'create database "{nome}"'))

    engine = create_engine(
        _url_do_banco(admin_url, nome),
        # Teto explícito: a corrida precisa de duas conexões simultâneas
        # (uma por transação) mais a do preparo. Passar disso seria bug.
        pool_size=4,
        max_overflow=0,
        connect_args={"options": f"-c statement_timeout={TIMEOUT_STATEMENT_MS}"},
    )
    with engine.begin() as conn:
        for migration in MIGRATIONS:
            sql = (MIGRATIONS_DIR / f"{migration}.sql").read_text(encoding="utf-8")
            conn.execute(text(sql))

    yield engine

    engine.dispose()
    with admin_engine.connect() as conn:
        conn.execute(text(f'drop database if exists "{nome}" with (force)'))


@pytest.fixture(autouse=True)
def banco_zerado(engine_conc: Engine) -> None:
    """Zera os dados (não o schema) antes de cada corrida.

    Varre `pg_tables` em vez de listar tabelas à mão: uma migration futura
    que traga tabela nova entraria na limpeza sozinha, e uma lista esquecida
    aqui significaria capital de uma corrida contando na seguinte — bug de
    isolamento que se manifesta como falha intermitente na corrida errada.
    Nenhuma migration insere dado de configuração, então não há semente a
    preservar (conferido em 2026-08-12).

    DESLIGA OS TRIGGERS DE USUÁRIO ANTES DE TRUNCAR, desde a migration 016.
    Até a 015, `truncate` atravessava as proteções append-only porque elas
    são triggers de LINHA e TRUNCATE não visita linhas — era um furo, e este
    fixture vivia dele. A 016 instalou BEFORE TRUNCATE em capital_ledger
    (OC007), tomador_documento (OC013), ocorrencia_atipicidade (OC014) e
    esc_capital_social (OC021); sem o `disable trigger user`, a segunda
    corrida do módulo morreria com OC007 ao tentar limpar o ledger que a
    primeira gravou.

    Ter que desligar explicitamente é o resultado desejado, não um
    contratempo: é a prova de que apagar essas trilhas deixou de ser
    alcançável por um comando de limpeza qualquer. `disable trigger user`
    (e não `all`) preserva os triggers internos de FK, que continuam
    fazendo o `cascade` funcionar. Este banco é descartável e criado por
    esta suíte — a manobra não existe em nenhum caminho de produção.
    """
    with engine_conc.begin() as conn:
        conn.execute(
            text(
                """
                do $$
                declare v_tabela text;
                begin
                    for v_tabela in select tablename from pg_tables where schemaname = 'public'
                    loop
                        execute format('alter table %I disable trigger user', v_tabela);
                    end loop;

                    for v_tabela in select tablename from pg_tables where schemaname = 'public'
                    loop
                        execute format('truncate table %I cascade', v_tabela);
                    end loop;

                    for v_tabela in select tablename from pg_tables where schemaname = 'public'
                    loop
                        execute format('alter table %I enable trigger user', v_tabela);
                    end loop;
                end $$;
                """
            )
        )


# ---------------------------------------------------------------------
# Montagem dos cenários
# ---------------------------------------------------------------------


def _constituir_capital(session: Session, valor: int) -> None:
    session.execute(
        text("insert into esc_capital_social (valor, tipo_evento) values (:v, 'constituicao')"),
        {"v": valor},
    )
    session.commit()


def _tomador_apto(session: Session, razao_social: str) -> uuid.UUID:
    """Tomador que passa por TODOS os gates de ativação vigentes.

    Município autorizado (OC002) e identificação arquivada (OC019, migration
    014). Sem o segundo, toda ativação destas corridas morreria antes de
    chegar ao teto e o teste provaria o gate errado.
    """
    tomador_id: uuid.UUID = session.execute(
        text(
            """
            insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
            values (:cnpj, :razao, 'ME', 'Formoso', 'GO', true)
            returning id
            """
        ),
        {"cnpj": f"{uuid.uuid4().int % 10**14:014d}", "razao": razao_social},
    ).scalar_one()
    session.commit()
    arquivar_identificacao(session, tomador_id)
    return tomador_id


def _operacao_registrada(session: Session, tomador_id: uuid.UUID, valor: int) -> uuid.UUID:
    """Operação em 'registrada' e com registro CONFIRMADO (OC004, migration 013)."""
    operacao_id: uuid.UUID = session.execute(
        text(
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values (:t, 'emprestimo', :v, 2.5, 'PRICE', 12, 'registrada', 'REG-CONC')
            returning id
            """
        ),
        {"t": str(tomador_id), "v": valor},
    ).scalar_one()
    session.commit()
    confirmar_registro(session, operacao_id)
    return operacao_id


def _operacao_ativa(session: Session, tomador_id: uuid.UUID, valor: int) -> uuid.UUID:
    operacao_id = _operacao_registrada(session, tomador_id, valor)
    session.execute(
        text("update operacao_credito set status = 'ativa' where id = :i"),
        {"i": str(operacao_id)},
    )
    session.commit()
    return operacao_id


def _ativar(operacao_id: uuid.UUID) -> Callable[[Session], None]:
    def tarefa(session: Session) -> None:
        session.execute(
            text("update operacao_credito set status = 'ativa' where id = :i"),
            {"i": str(operacao_id)},
        )

    return tarefa


def _status(engine: Engine, operacao_id: uuid.UUID) -> str:
    with engine.connect() as conn:
        status: str = conn.execute(
            text("select status from operacao_credito where id = :i"), {"i": str(operacao_id)}
        ).scalar_one()
    return status


def _capital_e_comprometido(engine: Engine) -> tuple[Decimal, Decimal]:
    """O par que define o invariante: comprometido nunca pode passar o capital."""
    with engine.connect() as conn:
        capital: Decimal = conn.execute(
            text("select capital_atual from v_capital_atual")
        ).scalar_one()
        comprometido: Decimal = conn.execute(
            text(
                "select coalesce(sum(valor_principal), 0) from operacao_credito "
                "where status in ('ativa','inadimplente')"
            )
        ).scalar_one()
    return capital, comprometido


# ---------------------------------------------------------------------
# O motor da corrida
# ---------------------------------------------------------------------


@dataclass
class Desfecho:
    """Como uma das transações da corrida terminou."""

    nome: str
    commitou: bool
    sqlstate: Optional[str]

    def __str__(self) -> str:
        return f"{self.nome}={'COMMIT' if self.commitou else f'ROLLBACK/{self.sqlstate}'}"


def _correr_em_paralelo(
    engine: Engine, tarefas: Dict[str, Callable[[Session], None]]
) -> Dict[str, Desfecho]:
    """Dispara cada tarefa em sua própria transação, todas soltas na barreira.

    Cada tarefa recebe uma Session própria (conexão própria) e NÃO commita:
    o commit é daqui, para que o desfecho registrado seja o da transação
    inteira e não o de uma statement isolada.
    """
    barreira = threading.Barrier(len(tarefas))
    fabrica = sessionmaker(bind=engine)
    desfechos: Dict[str, Desfecho] = {}
    trava = threading.Lock()

    def trabalhar(nome: str, tarefa: Callable[[Session], None]) -> None:
        session = fabrica()
        try:
            # Conexão aberta ANTES da barreira. Ver a nota sobre flakiness no
            # docstring do módulo: handshake depois da barreira dessincroniza
            # as threads e mata a corrida em silêncio.
            session.execute(text("select 1"))
            session.commit()

            barreira.wait(timeout=TIMEOUT_BARREIRA_S)

            tarefa(session)
            session.commit()
            desfecho = Desfecho(nome, True, None)
        # Capturar tudo é intencional: aqui o erro não é acidente, é o
        # resultado que se está medindo — o SQLSTATE do bloqueio.
        except Exception as exc:
            session.rollback()
            desfecho = Desfecho(nome, False, sqlstate_de(exc))
        finally:
            session.close()
        with trava:
            desfechos[nome] = desfecho

    threads = [
        threading.Thread(target=trabalhar, args=(nome, tarefa), name=nome)
        for nome, tarefa in tarefas.items()
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=TIMEOUT_THREAD_S)
        assert not thread.is_alive(), (
            f"a transação '{thread.name}' não terminou em {TIMEOUT_THREAD_S}s — "
            "sinal de advisory lock retido ou deadlock, não de lentidão."
        )

    assert set(desfechos) == set(tarefas), f"threads sem desfecho registrado: {desfechos}"
    return desfechos


def _um_commitou(desfechos: Dict[str, Desfecho]) -> None:
    """Exatamente uma das transações pode ter sobrevivido."""
    commitaram = [d.nome for d in desfechos.values() if d.commitou]
    assert len(commitaram) == 1, (
        "exatamente uma das transações concorrentes deveria commitar; "
        f"commitaram {commitaram}. Desfechos: {[str(d) for d in desfechos.values()]}"
    )


def _invariante_do_teto(engine: Engine) -> tuple[Decimal, Decimal]:
    """Afirma o Art. 5º sobre o estado final e devolve o par para asserções finas."""
    capital, comprometido = _capital_e_comprometido(engine)
    assert comprometido <= capital, (
        f"TETO VIOLADO: {comprometido} comprometidos contra capital de {capital}. "
        "É exatamente a falha F1 (Art. 5º, LC 167/2019) que o advisory lock existe para impedir."
    )
    return capital, comprometido


# ---------------------------------------------------------------------
# As quatro corridas
# ---------------------------------------------------------------------


class TestAtivacaoContraAtivacao:
    """A corrida original (F1): duas ativações que só cabem separadas."""

    def test_duas_ativacoes_simultaneas_e_so_uma_passa(self, engine_conc: Engine) -> None:
        with sessionmaker(bind=engine_conc)() as sessao:
            _constituir_capital(sessao, 50_000)
            op_a = _operacao_registrada(sessao, _tomador_apto(sessao, "Alvo A ME"), 30_000)
            op_b = _operacao_registrada(sessao, _tomador_apto(sessao, "Alvo B ME"), 30_000)

        desfechos = _correr_em_paralelo(
            engine_conc, {"ativacao_A": _ativar(op_a), "ativacao_B": _ativar(op_b)}
        )

        _um_commitou(desfechos)
        perdedor = next(d for d in desfechos.values() if not d.commitou)
        assert perdedor.sqlstate == "OC001", (
            "a ativação perdedora tinha que morrer no teto de capital (OC001), "
            f"e morreu com {perdedor.sqlstate}."
        )

        _, comprometido = _invariante_do_teto(engine_conc)
        assert comprometido == Decimal("30000.00")

        # O ledger é a prova documental: duas ativações contabilizadas seriam
        # o mesmo desastre com aparência de normalidade.
        with engine_conc.connect() as conn:
            entradas = conn.execute(
                text("select count(*) from capital_ledger where evento_tipo = 'ativacao_operacao'")
            ).scalar_one()
        assert entradas == 1, f"{entradas} entradas de ativação no ledger para uma única ativação."


class TestAtivacaoContraReducaoDeCapital:
    """Ativar consome o disponível; reduzir capital encolhe o disponível.

    Capital 50.000, operação de 30.000 esperando ativação, redução de 30.000
    esperando registro: as duas cabem sozinhas, juntas deixariam 30.000
    comprometidos sobre um capital de 20.000. Quem chega depois é recusada, e
    o SQLSTATE diz QUAL das duas chegou depois — por isso a asserção casa
    desfecho com código em vez de aceitar qualquer erro.
    """

    def test_ativacao_e_reducao_simultaneas_e_so_uma_passa(self, engine_conc: Engine) -> None:
        with sessionmaker(bind=engine_conc)() as sessao:
            _constituir_capital(sessao, 50_000)
            operacao = _operacao_registrada(sessao, _tomador_apto(sessao, "Alvo C ME"), 30_000)

        def reduzir(session: Session) -> None:
            session.execute(
                text("insert into esc_capital_social (valor, tipo_evento) values (30000,'reducao')")
            )

        desfechos = _correr_em_paralelo(
            engine_conc, {"ativacao": _ativar(operacao), "reducao": reduzir}
        )

        _um_commitou(desfechos)
        if desfechos["ativacao"].commitou:
            assert desfechos["reducao"].sqlstate == "OC005", (
                "a ativação venceu o lock, então a redução tinha que ser recusada por deixar o "
                f"capital abaixo do comprometido (OC005); veio {desfechos['reducao'].sqlstate}."
            )
        else:
            assert desfechos["ativacao"].sqlstate == "OC001", (
                "a redução venceu o lock, então a ativação tinha que morrer no teto já reduzido "
                f"(OC001); veio {desfechos['ativacao'].sqlstate}."
            )

        capital, comprometido = _invariante_do_teto(engine_conc)
        assert (capital, comprometido) in {
            (Decimal("50000.00"), Decimal("30000.00")),  # ativação venceu
            (Decimal("20000.00"), Decimal("0")),  # redução venceu
        }, f"estado final impossível: capital={capital}, comprometido={comprometido}"


class TestAtivacaoContraLiquidacao:
    """Liquidar devolve capital — mas só para quem ativar DEPOIS do commit.

    Capital 50.000, operação de 30.000 ativa e operação de 40.000 esperando:
    a segunda só cabe se a primeira já tiver saído. Liquidar nunca falha (o
    dinheiro está voltando); a ativação passa ou é recusada por OC001, e o
    que este teste recusa é o meio-termo — a ativação passar SEM a liquidação
    ter commitado, que é a leitura suja do comprometido.
    """

    def test_liquidacao_simultanea_nao_autoriza_ativacao_antecipada(
        self, engine_conc: Engine
    ) -> None:
        with sessionmaker(bind=engine_conc)() as sessao:
            _constituir_capital(sessao, 50_000)
            # Ativar aqui já é o caminho feliz do teto (30.000 sobre 50.000);
            # a corrida disputa a folga de 20.000 que sobra.
            ativa = _operacao_ativa(sessao, _tomador_apto(sessao, "Alvo D ME"), 30_000)
            # Desde a migration 017, liquidar é QUITAÇÃO e exige a agenda
            # inteira baixada contra movimento bancário (OC022). A corrida
            # continua sendo entre ativação e liquidação; o que muda é que a
            # liquidação precisa estar apta a acontecer antes de a corrida
            # começar — senão a thread perdedora não perderia por concorrência,
            # perderia por falta de lastro, e o teste deixaria de provar o que
            # promete.
            quitar_operacao(sessao, ativa)
            pretendente = _operacao_registrada(sessao, _tomador_apto(sessao, "Alvo E ME"), 40_000)

        def liquidar(session: Session) -> None:
            session.execute(
                text("update operacao_credito set status = 'liquidada' where id = :i"),
                {"i": str(ativa)},
            )

        desfechos = _correr_em_paralelo(
            engine_conc, {"ativacao": _ativar(pretendente), "liquidacao": liquidar}
        )

        assert desfechos["liquidacao"].commitou, (
            "liquidar devolve capital e não pode ser recusado; veio "
            f"{desfechos['liquidacao'].sqlstate}."
        )
        assert _status(engine_conc, ativa) == "liquidada"

        _, comprometido = _invariante_do_teto(engine_conc)
        if desfechos["ativacao"].commitou:
            assert _status(engine_conc, pretendente) == "ativa"
            assert comprometido == Decimal("40000.00")
        else:
            assert desfechos["ativacao"].sqlstate == "OC001", (
                "a ativação correu antes da liquidação commitar, então tinha que morrer no teto "
                f"(OC001); veio {desfechos['ativacao'].sqlstate}."
            )
            assert _status(engine_conc, pretendente) == "registrada"
            assert comprometido == Decimal("0")


class TestAtivacaoContraNovacao:
    """A TROCA da novação contra uma ativação comum, pelo mesmo capital.

    Desde a migration 026 a chamada de novação não move capital nenhum: ela
    só cria a substituta amarrada à original, que continua no comprometido.
    O capital se move na ATIVAÇÃO da substituta, e é ali que a corrida existe
    — num único commit a original sai do comprometido e a substituta entra,
    sob o mesmo `pg_advisory_xact_lock` das demais ativações.

    O risco a mais que a troca carrega, e a razão de esta corrida existir: ela
    LIBERA capital no meio do caminho. Se a liberação da original ficasse
    visível a uma ativação concorrente antes de a substituta ocupar o lugar,
    as duas passariam sobre o mesmo dinheiro — que é o furo da 026 em versão
    concorrente.
    """

    def test_troca_da_novacao_simultanea_nao_conta_capital_duas_vezes(
        self, engine_conc: Engine
    ) -> None:
        """Capital 50.000; original ativa de 30.000; substituta de 40.000
        (juros capitalizados) esperando ativação; pretendente de 20.000.

        Serializadas em qualquer ordem, as duas NÃO cabem, e por contas
        diferentes — o que torna a corrida uma prova e não uma coincidência:

          troca primeiro ..... comprometido 40.000, sobram 10.000; a
                               pretendente de 20.000 morre no teto;
          pretendente primeiro comprometido 50.000; a troca libera os 30.000
                               da original e ainda assim os 40.000 da
                               substituta não cabem nos 30.000 que sobraram.

        Passassem as duas, seriam 60.000 comprometidos sobre 50.000 de capital
        próprio: a violação do Art. 5º da LC 167/2019 que o lock impede.
        """
        with sessionmaker(bind=engine_conc)() as sessao:
            _constituir_capital(sessao, 50_000)
            original = _operacao_ativa(sessao, _tomador_apto(sessao, "Alvo F ME"), 30_000)
            substituta = sessao.execute(
                text("select fn_novar_operacao(:i, 40000, 2.5, 'PRICE', 24, 'REG-NOVACAO')"),
                {"i": str(original)},
            ).scalar_one()
            sessao.commit()
            # A substituta é um título novo: precisa do próprio registro
            # confirmado (OC004, migration 013) para chegar ao teto.
            confirmar_registro(sessao, substituta)
            pretendente = _operacao_registrada(sessao, _tomador_apto(sessao, "Alvo G ME"), 20_000)

        # Criar a substituta não moveu nada: é a original que ocupa o teto.
        assert _status(engine_conc, original) == "ativa"
        assert _capital_e_comprometido(engine_conc)[1] == Decimal("30000.00")

        desfechos = _correr_em_paralelo(
            engine_conc, {"ativacao": _ativar(pretendente), "troca": _ativar(substituta)}
        )

        commitaram = [d.nome for d in desfechos.values() if d.commitou]
        assert len(commitaram) == 1, (
            "as duas transações passaram sobre o mesmo capital — a troca da novação liberou "
            f"a original para uma ativação concorrente ver antes de a substituta ocupar o lugar ({desfechos})."
        )

        recusada = next(d for d in desfechos.values() if not d.commitou)
        assert recusada.sqlstate == "OC001", (
            "a perdedora tinha que morrer no teto (OC001), que é a conta do Art. 5º; "
            f"veio {recusada.sqlstate}."
        )

        _, comprometido = _invariante_do_teto(engine_conc)
        if desfechos["troca"].commitou:
            # A troca aconteceu inteira: a original saiu e a substituta entrou.
            assert _status(engine_conc, original) == "renegociada"
            assert _status(engine_conc, substituta) == "ativa"
            assert _status(engine_conc, pretendente) == "registrada"
            assert comprometido == Decimal("40000.00")
        else:
            # A troca foi recusada: ela é ATÔMICA, então a original não pode
            # ter ficado meio baixada. Metade de uma troca seria capital
            # liberado sem nada no lugar — o furo da 026 por um caminho novo.
            assert (
                _status(engine_conc, original) == "ativa"
            ), "a original saiu do comprometido numa troca que não se completou."
            assert _status(engine_conc, substituta) == "registrada"
            assert _status(engine_conc, pretendente) == "ativa"
            assert comprometido == Decimal("50000.00")

        # O ledger não pode guardar a metade de uma troca: 'renegociacao' e o
        # 'ativacao_operacao' da substituta andam juntos ou não andam.
        with engine_conc.connect() as conn:
            renegociacoes = conn.execute(
                text("select count(*) from capital_ledger where evento_tipo = 'renegociacao'")
            ).scalar_one()
            ativacoes_substituta = conn.execute(
                text(
                    "select count(*) from capital_ledger "
                    "where evento_tipo = 'ativacao_operacao' and operacao_id = :i"
                ),
                {"i": str(substituta)},
            ).scalar_one()
        assert renegociacoes == ativacoes_substituta == (1 if desfechos["troca"].commitou else 0)


if __name__ == "__main__":
    # Este arquivo DEIXOU de ser script standalone (`python tests/test_concorrencia.py <db>`).
    # Sem esta guarda, executá-lo assim definiria as fixtures, não rodaria teste
    # nenhum e sairia 0 — um verde falso, que é pior do que não ter o teste.
    raise SystemExit(
        "tests/test_concorrencia.py agora é um módulo pytest. Rode:\n"
        "  pytest tests/test_concorrencia.py -v\n"
        "com ORGCRED_TEST_DATABASE_URL apontando para o Postgres de teste.\n"
        "ATENÇÃO CI: o passo 'Rodar testes de concorrência (Python)' do job "
        "`integration` em .circleci/config.yml precisa ser removido — estas "
        "corridas passaram a rodar no job `unit-tests`, junto com o resto da suíte."
    )
