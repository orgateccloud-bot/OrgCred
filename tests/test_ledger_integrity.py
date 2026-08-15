"""
Testes da integridade do capital_ledger (migration 005, Fase 7):
proteção append-only e verificação da cadeia de hash.
"""

import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Generator, Iterator, List, Optional, Sequence, Tuple

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.capital_engine import ativar_operacao
from app.core.ledger_integrity import QuebraIntegridade, verificar_integridade_ledger
from tests.conftest import (
    MIGRATIONS,
    MIGRATIONS_DIR,
    _base_admin_url,
    arquivar_identificacao,
    confirmar_registro,
    sqlstate_de,
)


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


# ---------------------------------------------------------------------
# A ORDEM da cadeia: `seq`, e não `created_at` (migration 020)
# ---------------------------------------------------------------------
# `capital_ledger.created_at` tem default `now()`, e `now()` no Postgres é
# `transaction_timestamp()` — fixado quando a transação ABRE, não quando a
# linha é gravada. Até a 019, a cadeia de hash era encadeada por esse campo
# (005:53, `order by created_at desc, id desc`) e verificada por ele
# (005:107, `lag(...) over (order by l.created_at, l.id)`).
#
# Enquanto uma transação for curta o suficiente para que abrir e gravar
# sejam "o mesmo instante", os dois coincidem. Duas transações sobrepostas
# desfaziam a coincidência: quem abriu ANTES podia gravar DEPOIS, encadeando
# no hash de uma linha que a verificação reordenava para depois dela — e
# acusava AS DUAS de adulteração, numa cadeia que ninguém tocou.
#
# A migration 020 ancorou o encadeamento e a verificação em
# `capital_ledger.seq`, uma chave de sequência atribuída no INSERT: ordem de
# gravação, não relógio. `created_at` continua com default `now()` DE
# PROPÓSITO (ver a seção 6 da 020) — é justamente o que mantém este cenário
# reproduzível. Se alguém trocá-lo por `clock_timestamp()`, ou voltar a
# ordenar a cadeia por tempo, os dois testes abaixo dizem isso em voz alta em
# vez de deixar a regressão passar.
#
# Este bloco precisa de commits reais em DUAS conexões distintas: a
# `db_session` do conftest roda tudo dentro de uma transação revertida, e uma
# transação só tem UM `transaction_timestamp()`, então o cenário é
# inalcançável por lá. Daí um banco próprio, no mesmo padrão de
# tests/test_concorrencia.py — as linhas aqui são commitadas de verdade (é o
# ponto), e num banco compartilhado elas vazariam para os testes acima, que
# verificam o ledger INTEIRO.

# Rede de segurança contra travamento, não temporizador do cenário: aqui não
# há disputa de lock nenhuma (B commita antes de A tentar escrever). Se
# estourar, houve lock retido — melhor falhar com mensagem do que pendurar.
TIMEOUT_STATEMENT_MS = 30_000

# A migration que esta seção do arquivo cobre. Isolada numa constante porque
# ela é usada de DOIS jeitos opostos: aplicada junto das demais no cenário da
# corrida, e deliberadamente OMITIDA no cenário que constrói um ledger da era
# 019 para depois migrá-lo. `MIGRATIONS.index` levanta ValueError se o nome
# sumir da lista do conftest — erro de coleta, alto e imediato, em vez de um
# recorte silenciosamente errado.
MIGRATION_HASHCHAIN = "020_hashchain_monotonica"
MIGRATIONS_ANTES_DA_HASHCHAIN = MIGRATIONS[: MIGRATIONS.index(MIGRATION_HASHCHAIN)]


@contextmanager
def _banco_descartavel(prefixo: str) -> Iterator[Engine]:
    """Banco vazio, próprio, derrubado ao final — SEM migration aplicada.

    Quem aplica as migrations é o chamador, de propósito: um dos cenários
    daqui precisa parar na 019 para depois migrar, e uma fixture que já
    entregasse o schema pronto não teria como oferecer isso.
    """
    admin_url = _base_admin_url()
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    nome = f"orgcred_{prefixo}_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect() as conn:
        conn.execute(text(f'create database "{nome}"'))

    engine = create_engine(
        f"{admin_url.rsplit('/', 1)[0]}/{nome}",
        # Duas conexões simultâneas (uma por transação) mais a do preparo.
        pool_size=4,
        max_overflow=0,
        connect_args={"options": f"-c statement_timeout={TIMEOUT_STATEMENT_MS}"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'drop database if exists "{nome}" with (force)'))
        admin_engine.dispose()


def _aplicar(engine: Engine, migrations: Sequence[str]) -> None:
    """Aplica as migrations informadas, na ordem informada, numa transação só."""
    with engine.begin() as conn:
        for migration in migrations:
            sql = (MIGRATIONS_DIR / f"{migration}.sql").read_text(encoding="utf-8")
            conn.execute(text(sql))


@dataclass
class CorridaForaDeOrdem:
    """O estado do ledger depois de uma gravação fora de ordem.

    'A' é a transação que ABRIU PRIMEIRO e GRAVOU POR ÚLTIMO; 'B' abriu
    depois e gravou antes. 'Âncora' é uma ativação normal, sozinha, que
    commitou antes das duas — está aqui para que nenhuma das linhas
    disputadas seja a primeira da cadeia, e o defeito não possa ser
    confundido com tratamento de `prev_hash` nulo.
    """

    created_at_ancora: datetime
    created_at_a: datetime
    created_at_b: datetime
    current_hash_ancora: str
    current_hash_a: str
    current_hash_b: str
    prev_hash_a: str
    prev_hash_b: str
    seq_ancora: int
    seq_a: int
    seq_b: int
    total_linhas: int
    quebras: List[QuebraIntegridade]


def _tomador_apto(session: Session, razao_social: str) -> uuid.UUID:
    """Tomador que passa por todos os gates de ativação (OC002 e OC019)."""
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


def _gravar_fora_de_ordem(engine: Engine) -> CorridaForaDeOrdem:
    """Produz a inversão pelo caminho REAL de escrita no ledger.

    Nada de INSERT direto em `capital_ledger`: as três linhas nascem de
    `fn_check_teto_capital` numa ativação de operação, que é como toda linha
    de ledger nasce em produção. O que se manipula é só o RELÓGIO das
    transações — e nem isso por relógio nenhum, apenas pela ordem em que elas
    abrem e commitam.

    Não há `sleep` e não há barreira: as duas transações não disputam o
    advisory lock do gate (B commita inteira antes de A tentar escrever), o
    que torna o cenário determinístico. E é justamente esse o ponto
    incômodo — a inversão não exige uma corrida apertada, basta uma
    transação que LEIA antes de escrever, que é o formato de qualquer
    request que consulta o capital e então ativa.
    """
    with sessionmaker(bind=engine)() as prep:
        prep.execute(
            text(
                "insert into esc_capital_social (valor, tipo_evento) values (100000,'constituicao')"
            )
        )
        prep.commit()
        op_ancora = _criar_operacao(prep, _tomador_apto(prep, "Ancora ME"), 20_000)
        op_a = _criar_operacao(prep, _tomador_apto(prep, "Abre Antes ME"), 20_000)
        op_b = _criar_operacao(prep, _tomador_apto(prep, "Grava Antes ME"), 20_000)

        prep.execute(
            text("update operacao_credito set status = 'ativa' where id = :i"),
            {"i": str(op_ancora)},
        )
        prep.commit()

    conexao_a = engine.connect()
    conexao_b = engine.connect()
    try:
        # A abre PRIMEIRO. O `select 1` não é enfeite: o SQLAlchemy adia o
        # BEGIN até a primeira statement, e é o BEGIN que fixa o
        # `transaction_timestamp()` que `now()` devolverá pelo resto da
        # transação — inclusive no default de `created_at`, milissegundos
        # depois. Sem esta statement, A abriria de fato só no UPDATE lá
        # embaixo, os dois carimbos sairiam na ordem certa e o teste passaria
        # a provar coisa nenhuma.
        tx_a = conexao_a.begin()
        conexao_a.execute(text("select 1"))

        # B abre DEPOIS, grava e commita INTEIRA.
        tx_b = conexao_b.begin()
        conexao_b.execute(
            text("update operacao_credito set status = 'ativa' where id = :i"),
            {"i": str(op_b)},
        )
        tx_b.commit()

        # Só agora A grava. Em READ COMMITTED ela ENXERGA a linha de B já
        # commitada, encadeia corretamente no `current_hash` dela — e carimba
        # `created_at` com o instante em que A abriu, anterior ao de B.
        conexao_a.execute(
            text("update operacao_credito set status = 'ativa' where id = :i"),
            {"i": str(op_a)},
        )
        tx_a.commit()
    finally:
        conexao_a.close()
        conexao_b.close()

    with engine.connect() as conn:
        linhas = {
            row.operacao_id: row
            for row in conn.execute(
                text(
                    "select operacao_id, created_at, prev_hash, current_hash, seq "
                    "from capital_ledger"
                )
            ).all()
        }
        total: int = conn.execute(text("select count(*) from capital_ledger")).scalar_one()

    with sessionmaker(bind=engine)() as sessao:
        quebras = verificar_integridade_ledger(sessao)

    return CorridaForaDeOrdem(
        created_at_ancora=linhas[op_ancora].created_at,
        created_at_a=linhas[op_a].created_at,
        created_at_b=linhas[op_b].created_at,
        current_hash_ancora=linhas[op_ancora].current_hash,
        current_hash_a=linhas[op_a].current_hash,
        current_hash_b=linhas[op_b].current_hash,
        prev_hash_a=linhas[op_a].prev_hash,
        prev_hash_b=linhas[op_b].prev_hash,
        seq_ancora=linhas[op_ancora].seq,
        seq_a=linhas[op_a].seq,
        seq_b=linhas[op_b].seq,
        total_linhas=total,
        quebras=quebras,
    )


@pytest.fixture(scope="module")
def corrida_fora_de_ordem() -> Generator[CorridaForaDeOrdem, None, None]:
    """Banco descartável com as migrations aplicadas e o cenário já gravado.

    Escopo de módulo porque o cenário é UM só: os dois testes abaixo olham
    para o mesmo ledger de três linhas, um afirmando que a inversão foi
    mesmo produzida e o outro afirmando o que a verificação deveria dizer
    sobre ela.
    """
    with _banco_descartavel("ordem") as engine:
        _aplicar(engine, MIGRATIONS)
        yield _gravar_fora_de_ordem(engine)


class TestOrdemDaCadeiaSobTransacoesSobrepostas:
    def test_a_inversao_de_created_at_foi_mesmo_produzida(
        self, corrida_fora_de_ordem: CorridaForaDeOrdem
    ) -> None:
        """O cenário existe — e tem que continuar existindo.

        Ele é o guarda do teste seguinte, que afirma que a cadeia NÃO acusa
        adulteração aqui. Sozinha, aquela afirmação também seria satisfeita
        por um cenário que evaporou: se o default de `created_at` mudar para
        `clock_timestamp()`, ou o SQLAlchemy passar a abrir a transação de
        outro jeito, não haveria mais inversão nenhuma para sobreviver, e o
        teste seguinte passaria sem provar coisa alguma. As asserções daqui
        separam os dois desfechos: cenário que sumiu falha AQUI, com nome
        próprio.
        """
        corrida = corrida_fora_de_ordem

        assert corrida.total_linhas == 3, (
            "esperadas exatamente 3 linhas de ativação no ledger (âncora, A e B); "
            f"vieram {corrida.total_linhas}."
        )

        # A GRAVOU DEPOIS DE B — é o que o encadeamento comprova, e ele é o
        # único registro fiel da ordem real de inserção: A só pôde encadear
        # no hash de B porque B já estava commitada quando A escreveu.
        assert corrida.prev_hash_b == corrida.current_hash_ancora, (
            "B tinha que ter encadeado na âncora — se não encadeou, a ordem de gravação "
            "não foi a que este cenário pressupõe."
        )
        assert corrida.prev_hash_a == corrida.current_hash_b, (
            "A tinha que ter encadeado em B (gravou depois dela). Sem isso não há inversão "
            "para provar."
        )

        # ...E MESMO ASSIM CARIMBOU UM `created_at` ANTERIOR, porque `now()`
        # devolve o início da transação de A, que abriu antes de B.
        assert corrida.created_at_ancora < corrida.created_at_a, (
            "a âncora tinha que ser a mais antiga das três — o preparo commitou antes de "
            "qualquer das duas transações abrir."
        )
        assert corrida.created_at_a < corrida.created_at_b, (
            "A INVERSÃO NÃO OCORREU: created_at de A "
            f"({corrida.created_at_a.isoformat()}) não é anterior ao de B "
            f"({corrida.created_at_b.isoformat()}). O default de `created_at` deixou de ser "
            "`now()`/transaction_timestamp(), ou a transação de A passou a abrir só na "
            "escrita — de um jeito ou de outro, este arquivo parou de exercitar o cenário."
        )

    def test_a_chave_da_cadeia_segue_a_gravacao_e_nao_o_relogio(
        self, corrida_fora_de_ordem: CorridaForaDeOrdem
    ) -> None:
        """`seq` (migration 020) põe as três linhas na ordem em que foram GRAVADAS.

        É a afirmação central da correção, e ela é verificável sem passar
        pela verificação da cadeia: os `created_at` estão em uma ordem
        (âncora, A, B) e os `seq` estão em outra (âncora, B, A). A segunda é
        a real — o encadeamento, provado no teste anterior, concorda com ela.
        A cadeia agora é percorrida por esta, e é por isso que ela não acusa
        nada no teste seguinte.
        """
        corrida = corrida_fora_de_ordem

        assert corrida.seq_ancora < corrida.seq_b < corrida.seq_a, (
            "os `seq` tinham que sair na ordem de GRAVAÇÃO (âncora, B, A) e saíram "
            f"âncora={corrida.seq_ancora}, B={corrida.seq_b}, A={corrida.seq_a}. Se a ordem "
            "de `seq` passou a acompanhar `created_at`, a chave deixou de ser atribuída na "
            "gravação e a cadeia voltou a depender do relógio."
        )

    def test_gravacao_fora_de_ordem_nao_pode_acusar_adulteracao(
        self, corrida_fora_de_ordem: CorridaForaDeOrdem
    ) -> None:
        """Nenhuma linha foi tocada: a cadeia tem que se declarar íntegra.

        As três linhas foram gravadas pelo trigger, commitadas, e ninguém
        desabilitou trigger nem rodou UPDATE — ao contrário de
        `test_detecta_adulteracao_via_bypass_do_trigger`, que faz exatamente
        isso e cuja acusação é legítima. Aqui a acusação seria falsa, e é o
        falso positivo que corrói a prova: quem recebe 'linha possivelmente
        adulterada' de uma corrida benigna aprende a ignorar o alerta — e a
        partir daí a adulteração de verdade chega no meio do ruído.

        Até a migration 019 este teste FALHAVA, com as duas linhas disputadas
        acusadas de 'prev_hash não corresponde ao current_hash da linha
        anterior'. A 020 é o que o fez passar.
        """
        quebras = corrida_fora_de_ordem.quebras

        assert quebras == [], (
            "fn_verificar_cadeia_ledger() acusou adulteração numa cadeia que ninguém tocou. "
            f"Motivos devolvidos: {[(str(q.ledger_id), q.motivo) for q in quebras]}"
        )


# ---------------------------------------------------------------------
# A 020 aplicada sobre um ledger que JÁ EXISTE
# ---------------------------------------------------------------------
# O cenário acima constrói o banco com todas as migrations de uma vez, e por
# isso não diz nada sobre a parte perigosa da 020: o BACKFILL. `created_at`
# entra no digest (005:66) e os hashes gravados sob a 005 foram calculados
# percorrendo a cadeia na ordem `(created_at, id)`. Numerar as linhas
# antigas em QUALQUER outra ordem faria a verificação percorrer a cadeia por
# um caminho diferente daquele em que ela foi construída — ou seja,
# "consertar" a cadeia a invalidaria, que é o oposto exato do objetivo.
#
# Este bloco monta um ledger da era 019 (migrations até a 019, linhas
# gravadas pelo caminho real), fotografa hash por hash, aplica a 020 e
# fotografa de novo. Quatro perguntas, uma por teste: os hashes continuam os
# mesmos? a chave nova reproduz a ordem histórica? a cadeia continua íntegra?
# e — a que impede a correção de virar um cala-boca — ela ainda ACUSA uma
# adulteração de verdade?
_LINHAS_ANTES_DA_020 = 3

_FOTO_DO_LEDGER = text("""
    select id::text as id, prev_hash, current_hash
    from capital_ledger
    order by created_at, id
""")


@dataclass
class LedgerMigradoDa019:
    """Antes e depois da 020 sobre o MESMO ledger, mais a prova de detecção."""

    linhas_antes: List[Tuple[str, Optional[str], str]]
    linhas_depois: List[Tuple[str, Optional[str], str]]
    seq_por_id: Dict[str, int]
    quebras_apos_migracao: List[QuebraIntegridade]
    id_adulterado: str
    quebras_apos_adulteracao: List[QuebraIntegridade]


def _migrar_ledger_existente(engine: Engine) -> LedgerMigradoDa019:
    """Constrói um ledger na era 019, aplica a 020 e mede o que mudou."""
    _aplicar(engine, MIGRATIONS_ANTES_DA_HASHCHAIN)

    with sessionmaker(bind=engine)() as prep:
        prep.execute(
            text(
                "insert into esc_capital_social (valor, tipo_evento) values (100000,'constituicao')"
            )
        )
        prep.commit()
        # Uma transação por ativação, commitada antes da seguinte começar: é o
        # caso BEM-COMPORTADO de propósito. São estas as linhas cujo
        # `(created_at, id)` coincide com a ordem real de gravação e cujos
        # hashes o backfill precisa preservar. (O caso patológico — a
        # inversão — é assunto do bloco anterior, e a 020 não promete
        # reescrever o veredito histórico dele.)
        for n in range(_LINHAS_ANTES_DA_020):
            op_id = _criar_operacao(prep, _tomador_apto(prep, f"Anterior a 020 #{n} ME"), 20_000)
            prep.execute(
                text("update operacao_credito set status = 'ativa' where id = :i"),
                {"i": str(op_id)},
            )
            prep.commit()

    with engine.connect() as conn:
        antes = [(r.id, r.prev_hash, r.current_hash) for r in conn.execute(_FOTO_DO_LEDGER).all()]

    _aplicar(engine, [MIGRATION_HASHCHAIN])

    with engine.connect() as conn:
        depois = [(r.id, r.prev_hash, r.current_hash) for r in conn.execute(_FOTO_DO_LEDGER).all()]
        seq_por_id = {
            row.id: row.seq
            for row in conn.execute(text("select id::text as id, seq from capital_ledger")).all()
        }

    with sessionmaker(bind=engine)() as sessao:
        quebras_apos_migracao = verificar_integridade_ledger(sessao)

    # Adulteração REAL, pelo mesmo caminho de
    # `test_detecta_adulteracao_via_bypass_do_trigger`: quem tem privilégio
    # para desligar a guarda OC007 reescreve uma linha e a religa. O alvo é a
    # linha do MEIO — tem vizinha dos dois lados, então o resultado também
    # mostra que a acusação não vaza para elas.
    alvo = depois[len(depois) // 2][0]
    with sessionmaker(bind=engine)() as sessao:
        sessao.execute(
            text("alter table capital_ledger disable trigger trg_bloquear_update_ledger")
        )
        sessao.execute(
            text("update capital_ledger set valor = valor + 1 where id = :i"), {"i": alvo}
        )
        sessao.execute(text("alter table capital_ledger enable trigger trg_bloquear_update_ledger"))
        sessao.commit()
        quebras_apos_adulteracao = verificar_integridade_ledger(sessao)

    return LedgerMigradoDa019(
        linhas_antes=antes,
        linhas_depois=depois,
        seq_por_id=seq_por_id,
        quebras_apos_migracao=quebras_apos_migracao,
        id_adulterado=alvo,
        quebras_apos_adulteracao=quebras_apos_adulteracao,
    )


@pytest.fixture(scope="module")
def ledger_migrado_da_019() -> Generator[LedgerMigradoDa019, None, None]:
    """Banco próprio outra vez, e por um motivo diferente do anterior.

    Aqui não é isolamento de cadeia quebrada: é que o banco da suíte já nasce
    com a 020 aplicada, e o que este bloco precisa medir é justamente a
    TRANSIÇÃO — um ledger escrito sob a 005 sendo migrado. Só um banco que
    para na 019 oferece isso.
    """
    with _banco_descartavel("migracao020") as engine:
        yield _migrar_ledger_existente(engine)


class TestMigracao020SobreLedgerExistente:
    def test_hashes_gravados_antes_da_020_continuam_identicos(
        self, ledger_migrado_da_019: LedgerMigradoDa019
    ) -> None:
        """A migration não pode ter recalculado nada — e não recalculou.

        `seq` NÃO entra no digest, e o backfill escreve exclusivamente essa
        coluna. Se um hash mudasse aqui, a 020 teria reescrito a prova em vez
        de reordenar a leitura dela.
        """
        migrado = ledger_migrado_da_019

        assert len(migrado.linhas_antes) == _LINHAS_ANTES_DA_020, (
            f"esperadas {_LINHAS_ANTES_DA_020} linhas gravadas antes da 020; vieram "
            f"{len(migrado.linhas_antes)} — o cenário não montou o ledger da era 019."
        )
        assert migrado.linhas_depois == migrado.linhas_antes, (
            "a 020 alterou hash de linha pré-existente. Como `created_at` entra no digest e "
            "os hashes antigos foram calculados sobre a ordem (created_at, id), qualquer "
            "reescrita aqui invalida a cadeia inteira em vez de consertá-la."
        )

    def test_a_chave_nova_reproduz_a_ordem_historica(
        self, ledger_migrado_da_019: LedgerMigradoDa019
    ) -> None:
        """O backfill numera por `(created_at, id)` — a ordem dos hashes vigentes.

        Não é uma ordem razoável entre outras: é A ordem sobre a qual cada
        `current_hash` do histórico foi computado. Numerar por outra coisa
        faria a verificação percorrer a cadeia por um caminho que ela nunca
        teve.
        """
        migrado = ledger_migrado_da_019

        seqs_na_ordem_historica = [migrado.seq_por_id[id_] for id_, _, _ in migrado.linhas_antes]

        assert seqs_na_ordem_historica == sorted(seqs_na_ordem_historica), (
            "os `seq` do backfill não sobem na ordem (created_at, id): "
            f"{seqs_na_ordem_historica}. A cadeia passaria a ser verificada numa ordem "
            "diferente daquela em que foi construída."
        )
        assert len(set(seqs_na_ordem_historica)) == len(seqs_na_ordem_historica), (
            f"o backfill repetiu `seq`: {seqs_na_ordem_historica}. Chave duplicada dá dois "
            "predecessores possíveis para a mesma linha e a verificação vira não determinística."
        )

    def test_cadeia_continua_integra_apos_a_migracao(
        self, ledger_migrado_da_019: LedgerMigradoDa019
    ) -> None:
        """O teste que a 020 tinha mais chance de reprovar.

        Um backfill em ordem errada não dá erro nenhum na aplicação da
        migration: ele produz um ledger que passa a se declarar adulterado
        do nada, na primeira vez que alguém abrir `GET /auditoria`.
        """
        quebras = ledger_migrado_da_019.quebras_apos_migracao

        assert quebras == [], (
            "depois da 020 a cadeia acusou linhas que estavam íntegras antes dela. "
            f"Motivos devolvidos: {[(str(q.ledger_id), q.motivo) for q in quebras]}"
        )

    def test_adulteracao_real_continua_sendo_detectada(
        self, ledger_migrado_da_019: LedgerMigradoDa019
    ) -> None:
        """Uma cadeia que nunca acusa nada seria a correção mais fácil — e inútil.

        A 020 tira de circulação o falso positivo; se tirasse junto o
        verdadeiro, teria trocado um detector barulhento por um detector
        surdo, que é estritamente pior: o barulhento pelo menos era possível
        investigar.
        """
        migrado = ledger_migrado_da_019

        acusadas = {str(q.ledger_id) for q in migrado.quebras_apos_adulteracao}

        assert acusadas == {migrado.id_adulterado}, (
            "a linha reescrita com a guarda OC007 desligada tinha que ser a única acusada; "
            f"acusadas={sorted(acusadas)}, adulterada={migrado.id_adulterado}."
        )
        assert migrado.quebras_apos_adulteracao[0].motivo.startswith(
            "current_hash não bate com o recalculado"
        ), (
            "o motivo esperado é o do recálculo (a linha foi reescrita, a cadeia não foi "
            f"rompida); veio {migrado.quebras_apos_adulteracao[0].motivo!r}."
        )


# ---------------------------------------------------------------------
# O buraco que ancorar a cadeia em `seq` abriria — e que a 020 fecha junto
# ---------------------------------------------------------------------
# Enquanto a cadeia era percorrida por `created_at` (005:107), o carimbo
# estava, POR ACIDENTE, amarrado à posição da linha: uma linha nova gravada
# com `created_at` retroativo encadeava no hash da última linha, mas a
# verificação a reordenava para o passado e acusava a quebra. Ancorar a
# cadeia em `seq` desfaz esse amarrio — `seq` diz onde a linha ESTÁ, e
# nada mais confere o que ela DIZ sobre quando aconteceu.
#
# Sem contramedida, a 020 teria trocado um falso positivo por um falso
# NEGATIVO, que é a troca ruim: quem tivesse apenas privilégio de INSERT
# (nenhum `disable trigger`, nenhum UPDATE, nenhum DELETE — o atacante mais
# barato que existe) acrescentaria um lançamento forjado carimbado com
# qualquer data do passado, e `GET /auditoria` o exibiria no meio do
# histórico com a cadeia declarando ÍNTEGRO.
#
# A contramedida é uma linha na seção 4 da 020 — `new.created_at := now()`,
# tornando o banco o autor do carimbo, como já era dos hashes e do `seq`.
# Estes testes são o que impede que ela seja removida por parecer supérflua.


class TestCarimboDeTempoNaoEDitadoPorQuemEscreve:
    def test_created_at_passado_no_insert_e_sobrescrito_pelo_banco(
        self, db_session: Session
    ) -> None:
        """O INSERT pede 400 dias atrás; o banco grava o instante da transação.

        `now()` é o mesmo valor que o default da coluna já produzia desde a
        001, então nenhum caminho legítimo muda: os `insert into
        capital_ledger` das migrations 001-017 omitem `created_at`. O que
        muda é que passá-lo explicitamente deixa de ter efeito.
        """
        referencia = db_session.execute(text("select now()")).scalar_one()

        ledger_id = db_session.execute(
            text("""
                insert into capital_ledger
                    (evento_tipo, valor, saldo_disponivel_pos, usuario_id, created_at)
                values ('ativacao_operacao', 777777, 1, 'invasor', now() - interval '400 days')
                returning id
            """)
        ).scalar_one()

        gravado = db_session.execute(
            text("select created_at from capital_ledger where id = :i"), {"i": str(ledger_id)}
        ).scalar_one()

        assert gravado >= referencia, (
            "o `created_at` pedido no INSERT venceu o do banco: a linha foi gravada com "
            f"{gravado.isoformat()}, anterior ao início desta transação "
            f"({referencia.isoformat()}). Sem `new.created_at := now()` no trigger, e com a "
            "cadeia ancorada em `seq`, um lançamento antedatado passa na verificação — o "
            "falso positivo da 019 vira falso negativo."
        )

    def test_lancamento_antedatado_nao_consegue_existir_e_verificar_limpo(
        self, db_session: Session
    ) -> None:
        """A afirmação forense, e não só a mecânica do trigger.

        Uma cadeia íntegra só vale como prova se as linhas que ela abona
        forem honestas sobre QUANDO aconteceram. Aqui o atacante tenta
        exatamente o par proibido — linha com data do passado E cadeia
        limpa — e o teste afirma que os dois não coexistem: ou a data é a
        real, ou a verificação acusa.

        Note o que este teste NÃO usa: `disable trigger`. Ao contrário de
        `test_detecta_adulteracao_via_bypass_do_trigger`, que precisa de
        privilégio de dono da tabela, aqui basta INSERT.
        """
        referencia = db_session.execute(text("select now()")).scalar_one()

        ledger_id = db_session.execute(
            text("""
                insert into capital_ledger
                    (evento_tipo, valor, saldo_disponivel_pos, usuario_id, created_at)
                values ('ativacao_operacao', 777777, 1, 'invasor', now() - interval '400 days')
                returning id
            """)
        ).scalar_one()

        quebras = verificar_integridade_ledger(db_session)
        # Escopo na linha forjada, e não em `count(*) where created_at <
        # referencia`: a contagem global daria o mesmo veredito hoje só
        # porque este teste não usa fixture que grave no ledger, e passaria a
        # acusar linhas legítimas no dia em que alguém acrescentasse uma.
        antedatada = db_session.execute(
            text("select created_at < :ref from capital_ledger where id = :i"),
            {"ref": referencia, "i": str(ledger_id)},
        ).scalar_one()

        assert not (antedatada and quebras == []), (
            "a linha forjada ficou carimbada com um instante anterior ao início desta "
            "transação E a cadeia se declara íntegra. Essa é a combinação que a trilha não "
            "pode admitir: um lançamento forjado exibido como histórico, com o selo de "
            "integridade em cima."
        )


# ---------------------------------------------------------------------
# A outra metade da correção da 020, que não está escrita nela
# ---------------------------------------------------------------------
# `seq` resolve o defeito de ORDEM (created_at era o instante de abertura da
# transação e podia inverter), mas não resolve sozinho o de VISIBILIDADE.
# Duas transações sobrepostas que escrevessem no ledger SEM serialização
# ainda quebrariam a cadeia, por um caminho novo: T1 tira `seq` = 5 e não
# commita; T2 tira 6, não ENXERGA a linha 5 (READ COMMITTED), encadeia em 4 e
# commita; T1 commita. A `lag()` põe 5 entre 4 e 6 e acusa a linha 6 de
# cadeia rompida sem ninguém ter tocado nela — o mesmo falso positivo da 019
# com outra causa.
#
# O que impede isso é o `pg_advisory_xact_lock` do gate de capital: ele é de
# TRANSAÇÃO (só cai no commit) e é tomado ANTES do INSERT, então o `nextval`
# do default de `seq` — avaliado dentro do INSERT — já acontece na seção
# crítica. Ordem dos `seq` = ordem dos commits, e quem lê o elo anterior lê
# uma linha já commitada.
#
# Ou seja: o advisory lock deixou de ser só o guarda do teto do Art. 5º e
# passou a ser peça da hash-chain. Nada no código diz isso, e é o tipo de
# acoplamento que só aparece depois de removido. Este teste é o aviso: quem
# afrouxar a serialização, ou acrescentar um caminho de escrita no ledger que
# não a respeite, reprova aqui com o motivo por extenso.
_RE_INSERT_LEDGER = re.compile(r"insert\s+into\s+capital_ledger", re.IGNORECASE)
_RE_ADVISORY_LOCK = re.compile(r"pg_advisory_xact_lock", re.IGNORECASE)

# Consulta ao catálogo VIVO, não aos arquivos .sql: o que vale é a função que
# ficou de pé depois de todas as migrations, não o texto de qualquer uma
# delas. Um `create or replace` futuro que remova o lock é pego aqui mesmo
# que o arquivo da 017 continue intacto no disco.
_FUNCOES_PLPGSQL = text("""
    select p.proname as nome, pg_get_functiondef(p.oid) as corpo
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    join pg_language  l on l.oid = p.prolang
    where n.nspname = 'public'
      and l.lanname = 'plpgsql'
    order by p.proname
""")


class TestSerializacaoDoLedgerContinuaDePe:
    def test_todo_insert_no_ledger_acontece_sob_o_advisory_lock(self, db_session: Session) -> None:
        """Cada ramo que grava no ledger toma o lock ANTES de gravar.

        A contagem é o ponto, e não apenas "existe um lock em algum lugar
        acima": `fn_check_teto_capital` tem TRÊS ramos de escrita (ativação,
        saída do comprometido e baixa por prejuízo) e cada um abre com o seu
        próprio `pg_advisory_xact_lock`. Exigir que o k-ésimo INSERT tenha ao
        menos k locks antes dele é o que transforma este teste em guarda de
        um ramo NOVO: um quarto bloco de escrita acrescentado no fim da
        função sem tomar o lock passaria por "tem lock antes" — e reprova
        aqui.
        """
        funcoes = db_session.execute(_FUNCOES_PLPGSQL).all()

        escritoras = [f for f in funcoes if _RE_INSERT_LEDGER.search(f.corpo)]

        # Sem esta asserção o teste passaria vazio no dia em que a escrita no
        # ledger mudasse de forma (um `execute` dinâmico, outro nome de
        # tabela) — verde por não ter encontrado nada para verificar, que é o
        # jeito mais silencioso de um guarda morrer.
        assert escritoras, (
            "nenhuma função plpgsql do banco contém `insert into capital_ledger`. Ou a escrita "
            "no ledger saiu do banco (e a hash-chain deixou de cobrir o caminho real), ou este "
            "teste ficou cego porque o INSERT mudou de forma. Nos dois casos ele precisa de "
            "conserto — não de ser apagado."
        )

        desprotegidos: List[str] = []
        for funcao in escritoras:
            locks = [m.start() for m in _RE_ADVISORY_LOCK.finditer(funcao.corpo)]
            for k, insercao in enumerate(_RE_INSERT_LEDGER.finditer(funcao.corpo), start=1):
                anteriores = sum(1 for posicao in locks if posicao < insercao.start())
                if anteriores < k:
                    desprotegidos.append(
                        f"{funcao.nome}: o {k}º `insert into capital_ledger` tem só "
                        f"{anteriores} `pg_advisory_xact_lock` antes de si"
                    )

        assert not desprotegidos, (
            "há escrita no capital_ledger fora da seção crítica do gate de capital: "
            f"{desprotegidos}. Isso não quebra só o teto do Art. 5º — quebra a HASH-CHAIN. "
            "Sem a serialização, duas transações sobrepostas tiram `seq` consecutivos e a "
            "segunda não enxerga a linha da primeira (READ COMMITTED): encadeia no "
            "predecessor errado, e a verificação acusa adulteração numa linha que ninguém "
            "tocou. É o falso positivo que a migration 020 fechou, reaberto por outro lado."
        )
