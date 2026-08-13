"""
Baixa de recebimento amarrada a movimentação bancária (migrations 009 e 016).

O invariante central: não existe parcela paga sem linha de extrato. Se
existisse, bastaria um UPDATE para fazer a régua de inadimplência (008)
parar de ver o atraso de uma dívida que continua em aberto — uma carteira
podre passaria por saudável sem que nada no sistema registrasse a mentira.

A migration 016 fechou as bordas desse invariante, todas provadas aqui:
o status 'baixada' (aceito pelo CHECK da 007 e escrito por ninguém) saiu do
domínio, o lastro deixou de poder ser repontado depois da baixa, a baixa
passou a ter autor, e a colisão concorrente no índice único virou OC011 em
vez de 23505 cru.
"""

import threading
import time
import uuid
from datetime import date
from decimal import Decimal
from typing import Dict, Generator, Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.capital_engine import ativar_operacao, baixar_parcela, registrar_movimento_bancario
from app.core.exceptions import BaixaInvalida, MovimentoDuplicado
from tests.conftest import (
    MIGRATIONS,
    MIGRATIONS_DIR,
    _base_admin_url,
    arquivar_identificacao,
    confirmar_registro,
    sqlstate_de,
)


def _operacao_ativa(db_session: Session, tomador_id: uuid.UUID, parcelas: int = 12) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 0, 'PRICE', :n, 'registrada', 'REG-BAIXA')
        returning id
        """),
        {"t": str(tomador_id), "n": parcelas},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)
    return op_id


def _parcela(db_session: Session, op_id: uuid.UUID, numero: int):
    return db_session.execute(
        text("""
        select id, valor_total, status, movimento_id
        from parcela where operacao_id = :op and numero = :n
        """),
        {"op": str(op_id), "n": numero},
    ).one()


def _movimento(db_session: Session, valor: str, documento: str | None = None) -> uuid.UUID:
    return registrar_movimento_bancario(
        db_session,
        data_movimento=date.today(),
        valor=Decimal(valor),
        documento=documento or f"DOC-{uuid.uuid4().hex[:12]}",
    )


# ---------------------------------------------------------------------
# Caminho feliz
# ---------------------------------------------------------------------


def test_baixa_amarra_parcela_ao_movimento(db_session, tomador_autorizado, capital_constituido):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    mov = _movimento(db_session, str(p.valor_total))

    baixar_parcela(db_session, p.id, mov)

    depois = _parcela(db_session, op_id, 1)
    assert depois.status == "paga"
    assert depois.movimento_id == mov


def test_movimento_maior_cobre_a_parcela(db_session, tomador_autorizado, capital_constituido):
    """Juros de mora fazem o tomador pagar MAIS que o valor original. Exigir
    igualdade impediria a baixa de todo pagamento atrasado — justamente os
    que mais importam para a cobrança."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)

    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total + Decimal("50"))))

    assert _parcela(db_session, op_id, 1).status == "paga"


def test_baixa_tira_a_parcela_do_aging(db_session, tomador_autorizado, capital_constituido):
    """Fecha o ciclo da Frente 3: é a baixa com lastro — e só ela — que faz
    a operação sair do atraso."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)

    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    db_session.execute(
        text(
            "update parcela set vencimento = current_date - 60 where operacao_id = :id and numero = 1"
        ),
        {"id": str(op_id)},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()

    assert (
        db_session.execute(text("select fn_dias_atraso(:id)"), {"id": str(op_id)}).scalar_one()
        == 60
    )

    p = _parcela(db_session, op_id, 1)
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    assert (
        db_session.execute(text("select fn_dias_atraso(:id)"), {"id": str(op_id)}).scalar_one() == 0
    )


# ---------------------------------------------------------------------
# O invariante: não há paga sem lastro
# ---------------------------------------------------------------------


def test_marcar_paga_direto_no_banco_e_recusado(
    db_session, tomador_autorizado, capital_constituido
):
    """A garantia é do trigger, não da aplicação: nem por SQL direto se dá
    uma parcela por paga sem movimento bancário."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set status = 'paga' where operacao_id = :id and numero = 1"),
            {"id": str(op_id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()


def test_movimento_nao_pode_baixar_duas_parcelas(
    db_session, tomador_autorizado, capital_constituido
):
    """Sem esta trava, um único crédito de R$ 1.000 no extrato baixaria dez
    parcelas — a carteira inteira ficaria "paga" com o dinheiro de uma."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p1 = _parcela(db_session, op_id, 1)
    p2 = _parcela(db_session, op_id, 2)
    mov = _movimento(db_session, "99999")

    baixar_parcela(db_session, p1.id, mov)

    with pytest.raises(BaixaInvalida, match="já foi usado"):
        baixar_parcela(db_session, p2.id, mov)
    assert _parcela(db_session, op_id, 2).status == "aberta"


def test_movimento_menor_que_a_parcela_e_recusado(
    db_session, tomador_autorizado, capital_constituido
):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)

    with pytest.raises(BaixaInvalida, match="não cobre a parcela"):
        baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total - Decimal("1"))))


def test_parcela_ja_baixada_nao_aceita_nova_baixa(
    db_session, tomador_autorizado, capital_constituido
):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    with pytest.raises(BaixaInvalida, match="não está em aberto"):
        baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))


def test_baixa_e_terminal(db_session, tomador_autorizado, capital_constituido):
    """Voltar uma parcela paga para aberta apagaria o lastro em silêncio.
    Não há estorno definido — a correção se faz no extrato (ver 009)."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set status = 'aberta' where id = :id"), {"id": str(p.id)}
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()


def test_parcela_ou_movimento_inexistente(db_session, tomador_autorizado, capital_constituido):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)

    with pytest.raises(BaixaInvalida, match="não existe"):
        baixar_parcela(db_session, uuid.uuid4(), _movimento(db_session, "9999"))

    with pytest.raises(BaixaInvalida, match="não existe"):
        baixar_parcela(db_session, p.id, uuid.uuid4())


# ---------------------------------------------------------------------
# Movimento bancário
# ---------------------------------------------------------------------


def test_documento_duplicado_e_recusado(db_session):
    """Idempotência da importação: reimportar o mesmo extrato — rotina na
    operação real — não pode duplicar crédito."""
    _movimento(db_session, "1000", documento="FITID-123")

    # Código próprio (MOVIMENTO_DUPLICADO, HTTP 409) e não OC011: documento
    # repetido não é "baixa sem lastro". Enquanto os dois compartilhavam
    # código, o dicionário do frontend mandava conferir o extrato atrás de um
    # movimento inexistente — quando o movimento existe, e é justamente por
    # isso que a segunda importação foi recusada.
    with pytest.raises(MovimentoDuplicado, match="Já existe um movimento"):
        _movimento(db_session, "1000", documento="FITID-123")


def test_movimento_e_imutavel(db_session):
    """Extrato é fato de fora: quem corrige é o banco, com outro lançamento."""
    mov = _movimento(db_session, "1000")

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update movimento_bancario set valor = 1 where id = :id"), {"id": str(mov)}
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC012"
    db_session.rollback()


# ---------------------------------------------------------------------
# Migration 016 (a): o domínio de status da parcela
# ---------------------------------------------------------------------


def test_status_baixada_nao_existe_mais(db_session, tomador_autorizado, capital_constituido):
    """O furo (a): 'baixada' era aceito pelo CHECK da 007, escrito por
    ninguém, e atravessava as três guardas da 009 — todas escritas sobre
    'paga'. Um UPDATE de uma palavra tirava a parcela do atraso
    (fn_dias_atraso só olha 'aberta') E da receita tributável no regime
    caixa (fn_apurar_trimestre só soma 'paga'), sem lastro e sem erro."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set status = 'baixada' where operacao_id = :id and numero = 1"),
            {"id": str(op_id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()

    assert _parcela(db_session, op_id, 1).status == "aberta"


def test_status_baixada_recusado_mesmo_com_lastro(
    db_session, tomador_autorizado, capital_constituido
):
    """Fecha a saída pela metade: 'baixada' COM movimento passaria pela regra
    de lastro e continuaria invisível para aging e apuração — um segundo nome
    para 'paga', indistinguível de erro de digitação."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    mov = _movimento(db_session, str(p.valor_total))

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set status = 'baixada', movimento_id = :m where id = :id"),
            {"m": str(mov), "id": str(p.id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()


def test_dominio_resiste_ao_trigger_desligado(db_session, tomador_autorizado, capital_constituido):
    """Por que a 016 pôs CHECK constraint além do trigger.

    Este mesmo arquivo desliga `trg_parcela_imutavel` para antedatar um
    vencimento (test_baixa_tira_a_parcela_do_aging) — o que prova que uma
    guarda que vive só em trigger é desligável por uma linha de SQL. Com o
    trigger fora, quem recusa é a constraint, com 23514.
    """
    op_id = _operacao_ativa(db_session, tomador_autorizado)

    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    try:
        with pytest.raises(Exception) as exc:
            db_session.execute(
                text(
                    "update parcela set status = 'baixada' where operacao_id = :id and numero = 1"
                ),
                {"id": str(op_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "23514"
    finally:
        db_session.rollback()
        db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
        db_session.commit()


def test_paga_sem_lastro_resiste_ao_trigger_desligado(
    db_session, tomador_autorizado, capital_constituido
):
    """A outra metade do CHECK: sair de 'aberta' sem movimento é recusado
    pelo banco mesmo sem o trigger — é o invariante central da 009 deixando
    de depender de um objeto que se desliga."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)

    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    try:
        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("update parcela set status = 'paga' where operacao_id = :id and numero = 1"),
                {"id": str(op_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "23514"
    finally:
        db_session.rollback()
        db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
        db_session.commit()


# ---------------------------------------------------------------------
# Migration 016 (b): o lastro não se repõe
# ---------------------------------------------------------------------


def test_movimento_nao_pode_ser_soltado(db_session, tomador_autorizado, capital_constituido):
    """O furo (b), na sua forma mais barata: zerar movimento_id devolve o
    crédito a v_movimentos_disponiveis (pronto para baixar outra parcela) e
    deixa a primeira 'paga' pendurada em nada."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set movimento_id = null where id = :id"), {"id": str(p.id)}
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()

    assert _parcela(db_session, op_id, 1).movimento_id is not None


def test_movimento_nao_pode_ser_repontado(db_session, tomador_autorizado, capital_constituido):
    """A forma sofisticada do mesmo furo: trocar o movimento reescreve, meses
    depois, contra qual dinheiro a dívida foi quitada — sem que a parcela
    saia de 'paga' um instante sequer."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    original = _movimento(db_session, str(p.valor_total))
    outro = _movimento(db_session, str(p.valor_total))
    baixar_parcela(db_session, p.id, original)

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set movimento_id = :m where id = :id"),
            {"m": str(outro), "id": str(p.id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()

    assert _parcela(db_session, op_id, 1).movimento_id == original


# ---------------------------------------------------------------------
# Migration 016 (d): a baixa tem autor
# ---------------------------------------------------------------------


def test_baixa_grava_autor(db_session, tomador_autorizado, capital_constituido):
    """A baixa é o único ato irreversível do ciclo (não há estorno definido)
    e era o único sem nome de gente. Sem autor, uma conciliação errada é
    permanente e não há a quem perguntar."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    autor = str(uuid.uuid4())

    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)), usuario_id=autor)

    gravado = db_session.execute(
        text("select baixado_por from parcela where id = :id"), {"id": str(p.id)}
    ).scalar_one()
    assert gravado == autor


def test_baixa_sem_usuario_continua_valendo(db_session, tomador_autorizado, capital_constituido):
    """Caminho feliz do outro lado: importação de OFX e script de correção não
    têm usuário autenticado, e recusar a baixa por isso pararia a conciliação.
    Autor NULL, no padrão da 004 — e NULL de verdade, não string vazia (o
    `nullif` existe porque uma GUC de classe 'app' volta a '' na conexão de
    pool, não a NULL)."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)

    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)))

    gravado = db_session.execute(
        text("select baixado_por from parcela where id = :id"), {"id": str(p.id)}
    ).scalar_one()
    assert gravado is None
    assert _parcela(db_session, op_id, 1).status == "paga"


def test_autoria_da_baixa_nao_se_reescreve(db_session, tomador_autorizado, capital_constituido):
    """Trilha de autoria editável não é trilha, é um campo de texto."""
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    autor = str(uuid.uuid4())
    baixar_parcela(db_session, p.id, _movimento(db_session, str(p.valor_total)), usuario_id=autor)

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text("update parcela set baixado_por = 'outra pessoa' where id = :id"),
            {"id": str(p.id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC011"
    db_session.rollback()

    assert (
        db_session.execute(
            text("select baixado_por from parcela where id = :id"), {"id": str(p.id)}
        ).scalar_one()
        == autor
    )


# ---------------------------------------------------------------------
# Migration 016 (e): baixa concorrente devolve código tratado, não 500
# ---------------------------------------------------------------------
# Precisa de commits reais em conexões distintas: a fixture `db_session` roda
# tudo dentro de uma transação revertida, e o furo aqui é justamente o que
# uma transação NÃO enxerga da outra. Mesmo desenho de
# tests/test_concorrencia.py — banco próprio, descartado ao fim do módulo —
# porque commitar no banco compartilhado vazaria capital para os testes que
# rodam em transação revertida.


# Redes de segurança contra travamento, não temporizadores da corrida (mesma
# disciplina de tests/test_concorrencia.py): a colisão do índice único resolve
# em milissegundos assim que a vencedora commita. Se algum destes estourar,
# houve deadlock ou lock não liberado.
TIMEOUT_CORRIDA_S = 30.0
TIMEOUT_THREAD_S = 60.0


@pytest.fixture(scope="module")
def engine_baixa() -> Generator[Engine, None, None]:
    """Banco só desta corrida, com todas as migrations aplicadas."""
    admin_url = _base_admin_url()
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    nome = f"orgcred_baixa_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect() as conn:
        conn.execute(text(f'create database "{nome}"'))

    engine = create_engine(
        f"{admin_url.rsplit('/', 1)[0]}/{nome}",
        # Três conexões simultâneas: a transação que segura a baixa, a que
        # tenta a segunda, e a que observa o bloqueio em pg_stat_activity.
        pool_size=4,
        max_overflow=0,
        connect_args={"options": "-c statement_timeout=30000"},
    )
    with engine.begin() as conn:
        for migration in MIGRATIONS:
            conn.execute(text((MIGRATIONS_DIR / f"{migration}.sql").read_text(encoding="utf-8")))

    yield engine

    engine.dispose()
    with admin_engine.connect() as conn:
        conn.execute(text(f'drop database if exists "{nome}" with (force)'))
    admin_engine.dispose()


def _esperar_backend_bloqueado(
    engine: Engine, thread: threading.Thread, resultado: Dict[str, Optional[BaseException]]
) -> None:
    """Espera até a transação da thread travar atrás da outra.

    É espera por CONDIÇÃO, não temporizador: sem ela, o commit da primeira
    transação poderia acontecer antes de a segunda ter passado pela checagem
    otimista de `fn_baixar_parcela` — e aí a recusa viria daquela checagem,
    não da colisão do índice único, e o teste passaria sem tocar no caminho
    que a 016 acrescentou.

    A saída por `not thread.is_alive()` é obrigatória, e não conveniência:
    se a perdedora morrer por um motivo qualquer (schema diferente do
    esperado, conexão recusada), ela nunca vai aparecer bloqueada, e sem esta
    checagem o laço só terminaria no timeout — escondendo o erro real atrás
    de "a corrida não aconteceu". O que se afirma depois, sobre `resultado`,
    é o desfecho de verdade.

    A conexão de observação é aberta UMA vez: `engine.connect()` a cada
    iteração devolveria e retomaria conexão do pool centenas de vezes por
    segundo enquanto duas das quatro do pool já estão presas na corrida.
    """
    limite = time.monotonic() + TIMEOUT_CORRIDA_S
    with engine.connect() as observador:
        while time.monotonic() < limite:
            if not thread.is_alive():
                return
            bloqueados = observador.execute(
                text("""
                select count(*) from pg_stat_activity
                 where datname = current_database()
                   and cardinality(pg_blocking_pids(pid)) > 0
                """)
            ).scalar_one()
            observador.rollback()
            if bloqueados:
                return
            time.sleep(0.02)
    raise AssertionError(
        f"nenhuma transação ficou bloqueada em até {TIMEOUT_CORRIDA_S}s e a perdedora segue "
        f"viva — a corrida não chegou a existir. Último resultado registrado: {resultado}"
    )


def test_baixa_concorrente_devolve_codigo_tratado(engine_baixa: Engine) -> None:
    """Duas baixas simultâneas com o MESMO movimento.

    O `if exists (...)` de fn_baixar_parcela roda em READ COMMITTED e não vê a
    baixa que a outra transação ainda não commitou: as duas passam pela
    checagem otimista e a perdedora morre no índice único. Antes da 016 isso
    chegava à API como 23505 — SQLSTATE fora do PGCODE_MAP, ou seja, HTTP 500
    "erro interno" para uma situação de negócio corriqueira, que o suporte
    investigaria como incidente.
    """
    fabrica = sessionmaker(bind=engine_baixa)

    with fabrica() as prep:
        prep.execute(
            text(
                "insert into esc_capital_social (valor, tipo_evento) values (50000,'constituicao')"
            )
        )
        prep.commit()
        tomador_id = prep.execute(
            text("""
            insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
            values (:cnpj, 'Concorrente ME', 'ME', 'Formoso', 'GO', true)
            returning id
            """),
            {"cnpj": f"{uuid.uuid4().int % 10**14:014d}"},
        ).scalar_one()
        prep.commit()
        arquivar_identificacao(prep, tomador_id)

        op_id = prep.execute(
            text("""
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values (:t, 'emprestimo', 12000, 0, 'PRICE', 12, 'registrada', 'REG-CONC-BAIXA')
            returning id
            """),
            {"t": str(tomador_id)},
        ).scalar_one()
        prep.commit()
        confirmar_registro(prep, op_id)
        ativar_operacao(prep, op_id)

        p1, p2 = (
            prep.execute(
                text("""
            select id from parcela where operacao_id = :o and numero in (1, 2) order by numero
            """),
                {"o": str(op_id)},
            )
            .scalars()
            .all()
        )
        movimento = prep.execute(
            text("""
            insert into movimento_bancario (data_movimento, valor, documento)
            values (current_date, 99999, :doc) returning id
            """),
            {"doc": f"DOC-CONC-{uuid.uuid4().hex[:10]}"},
        ).scalar_one()
        prep.commit()

    vencedora = fabrica()
    vencedora.execute(
        text("select fn_baixar_parcela(:p, :m)"), {"p": str(p1), "m": str(movimento)}
    )  # deliberadamente SEM commit: é o estado que a outra transação não enxerga

    resultado: Dict[str, Optional[BaseException]] = {}

    def perdedora() -> None:
        with fabrica() as sessao:
            try:
                baixar_parcela(sessao, p2, movimento)
                resultado["erro"] = None
            # Capturar tudo é intencional: o erro AQUI é o resultado medido.
            except BaseException as exc:  # noqa: BLE001
                resultado["erro"] = exc

    thread = threading.Thread(target=perdedora, name="baixa_perdedora")
    thread.start()
    try:
        _esperar_backend_bloqueado(engine_baixa, thread, resultado)
        vencedora.commit()
    finally:
        thread.join(timeout=TIMEOUT_THREAD_S)
        vencedora.close()

    assert not thread.is_alive(), "a baixa perdedora não terminou — advisory lock retido?"

    erro = resultado["erro"]
    assert isinstance(erro, BaixaInvalida), (
        "a baixa perdedora tinha que voltar como BaixaInvalida (OC011, HTTP 422); "
        f"veio {erro!r} — SQLSTATE {sqlstate_de(erro) if erro else None}."
    )
    assert erro.sqlstate == "OC011"
    assert "concorrente" in str(erro)

    with engine_baixa.connect() as conn:
        baixadas = conn.execute(
            text("select count(*) from parcela where movimento_id = :m"), {"m": str(movimento)}
        ).scalar_one()
    assert baixadas == 1, f"{baixadas} parcelas baixadas com o mesmo crédito."


def test_movimento_conciliado_sai_dos_disponiveis(
    db_session, tomador_autorizado, capital_constituido
):
    op_id = _operacao_ativa(db_session, tomador_autorizado)
    p = _parcela(db_session, op_id, 1)
    mov = _movimento(db_session, str(p.valor_total))

    assert (
        db_session.execute(
            text("select count(*) from v_movimentos_disponiveis where id = :id"), {"id": str(mov)}
        ).scalar_one()
        == 1
    )

    baixar_parcela(db_session, p.id, mov)

    assert (
        db_session.execute(
            text("select count(*) from v_movimentos_disponiveis where id = :id"), {"id": str(mov)}
        ).scalar_one()
        == 0
    )
