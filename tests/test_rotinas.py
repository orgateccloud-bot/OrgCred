"""
Executor de rotinas periódicas (app/rotinas.py).

O QUE ESTE ARQUIVO PRECISA PROVAR, em ordem de gravidade:

1. QUE UMA FALHA NÃO DERRUBA AS OUTRAS. Se um backup que falha impedisse a
   régua de rodar, o executor teria transformado um incidente isolado em
   inadimplência declarada com atraso — pior do que as quatro rotinas soltas
   que ele veio substituir.
2. QUE O CÓDIGO DE SAÍDA É != 0 QUANDO ALGO FALHA. É o único sinal que o
   Railway lê. Um executor que sempre sai 0 é uma rotina quebrando em silêncio
   com aparência de cobertura.
3. QUE A REGRA MENSAL NÃO PULA MÊS. Inclusive — e principalmente — nos meses
   sem dia 31, que é onde todo critério de "dia fixo" desaparece sem avisar.
4. QUE AS ROTINAS DE BANCO SÃO IDEMPOTENTES. Contra Postgres real, não contra
   a promessa do docstring.

Os testes de shell (`rodar_script`) usam `bash` de verdade e são pulados onde
ele não existe. O resto não depende de shell nenhum: `rodar_script` é
substituído, porque o que se está provando ali é a decisão do executor, não a
capacidade do sistema operacional de rodar um script.
"""

import io
import json
import logging
import shutil
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app import rotinas
from app.capital_engine import ativar_operacao
from app.core.logging import configure_logging
from app.core.security import get_current_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from app.rotinas import (
    LIMITE_ATRASO_HORAS,
    NOME_AGING,
    NOME_ATIPICIDADES,
    NOME_BACKUP,
    NOME_RESTORE_TEST,
    RESULTADO_DISPENSADA,
    RESULTADO_FALHA,
    RESULTADO_SUCESSO,
    ROTINAS_CONHECIDAS,
    TIMEOUT_BACKUP_S,
    TIMEOUT_RESTORE_TEST_S,
    Resultado,
    Rotina,
    RotinaError,
    competencia,
    deve_rodar_restore_test,
    diretorio_de_backups,
    diretorio_de_scripts,
    executar_aging,
    executar_atipicidades,
    executar_backup,
    executar_restore_test,
    executar_rotinas,
    main,
    montar_plano,
    registrar_execucao,
    registrar_execucao_no_banco,
    resultado_para_trilha,
    rodar_script,
)
from tests.conftest import confirmar_registro, envelhecer_execucao_rotina, sqlstate_de
from tests.test_logging import _estado_de_logging_preservado


sem_bash = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="bash indisponível — o executor roda em contêiner Linux, onde ele existe",
)


@pytest.fixture()
def logging_isolado():
    """Devolve o root logger ao estado anterior — ver tests/test_logging.py.

    Reaproveitado de lá, e não recopiado: a lógica de restauração é sutil (o
    handler da aplicação é REAPONTADO, não empilhado) e uma segunda cópia
    ligeiramente errada silenciaria o log de toda a suíte que rodar depois
    desta.
    """
    with _estado_de_logging_preservado():
        yield


@pytest.fixture(autouse=True)
def trilha_em_memoria(monkeypatch: pytest.MonkeyPatch) -> list[Resultado]:
    """Desvia a escrituração da trilha (migration 025) para uma lista.

    AUTOUSE porque `executar_rotinas` passou a gravar cada resultado em
    `execucao_rotina`, e a maior parte deste arquivo prova DECISÕES DO EXECUTOR
    com rotinas de mentira, sem Postgres nenhum. Sem o desvio, cada uma dessas
    execuções tentaria abrir sessão contra o banco configurado — lento no
    melhor caso, e um teste de decisão falhando por indisponibilidade de
    infraestrutura no pior.

    O desvio é sobre o ATRIBUTO DO MÓDULO, e é por isso que `executar_rotinas`
    resolve o default no corpo em vez de na assinatura. Quem precisa da função
    de verdade — `TestRegistrarExecucaoNoBanco` e os testes contra Postgres —
    usa o nome importado no topo deste arquivo, que aponta para o objeto
    original e não é alcançado por este `setattr`.

    Devolve a lista para os testes que querem afirmar O QUE seria gravado.
    """
    gravadas: list[Resultado] = []

    def gravar(resultado: Resultado) -> bool:
        gravadas.append(resultado)
        return True

    monkeypatch.setattr(rotinas, "registrar_execucao_no_banco", gravar)
    return gravadas


def _linhas(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in buffer.getvalue().splitlines() if linha.strip()]


def _saida_estruturada(capsys: pytest.CaptureFixture) -> list[dict[str, Any]]:
    """Linhas JSON emitidas em stdout — a saída que o Railway agrega."""
    return [json.loads(linha) for linha in capsys.readouterr().out.splitlines() if linha.strip()]


# ---------------------------------------------------------------------
# Competência e a regra mensal do restore-test
# ---------------------------------------------------------------------


class TestCompetencia:
    def test_formata_com_mes_de_dois_digitos(self):
        assert competencia(date(2027, 3, 9)) == "2027-03"

    def test_dezembro_nao_vira_do_ano(self):
        assert competencia(date(2027, 12, 31)) == "2027-12"


class TestRegraMensal:
    def test_sem_marcador_roda(self, tmp_path):
        assert deve_rodar_restore_test(date(2027, 3, 9), tmp_path / "nao_existe") is True

    def test_marcador_da_competencia_corrente_nao_roda(self, tmp_path):
        marcador = tmp_path / "marcador"
        marcador.write_text("2027-03\n", encoding="utf-8")
        assert deve_rodar_restore_test(date(2027, 3, 28), marcador) is False

    def test_marcador_de_competencia_anterior_roda(self, tmp_path):
        marcador = tmp_path / "marcador"
        marcador.write_text("2027-02\n", encoding="utf-8")
        assert deve_rodar_restore_test(date(2027, 3, 1), marcador) is True

    def test_marcador_ilegivel_roda(self, tmp_path):
        """Fail-open: o custo de um teste a mais é menor que o de nenhum."""
        marcador = tmp_path / "marcador"
        marcador.mkdir()  # diretório onde deveria haver arquivo -> OSError na leitura
        assert deve_rodar_restore_test(date(2027, 3, 9), marcador) is True

    def test_marcador_com_bytes_invalidos_roda(self, tmp_path):
        """A OUTRA família de 'ilegível', a que não é `OSError`.

        Escrita interrompida pela metade, setor corrompido no volume, variável
        apontada para o arquivo errado: o conteúdo deixa de ser UTF-8 e
        `read_text` levanta `UnicodeDecodeError` — subclasse de `ValueError`,
        não de `OSError`. Antes da correção isso escapava de
        `deve_rodar_restore_test` e derrubava a rotina inteira: o teste mensal
        de restauração parava de acontecer, com uma linha vermelha falando de
        codec sobre um arquivo de três bytes, longe do backup que ninguém mais
        estava testando. Fail-open vale para as duas famílias ou não vale.
        """
        marcador = tmp_path / "marcador"
        marcador.write_bytes(b"\xff\xfe\x00lixo")
        assert deve_rodar_restore_test(date(2027, 3, 9), marcador) is True

    def test_um_ano_de_execucoes_diarias_da_exatamente_uma_por_mes(self, tmp_path):
        """A borda do dia 31, provada pela ausência dela.

        2027 tem cinco meses sem dia 31 (fev, abr, jun, set, nov). Um critério
        `hoje.day == 31` cobriria sete dos doze meses e o painel não mostraria
        falha nenhuma nos outros cinco — não houve execução para falhar. Aqui o
        ano inteiro é percorrido dia a dia e o resultado tem de ser doze
        execuções, uma por competência, na ordem.
        """
        marcador = tmp_path / rotinas.MARCADOR_RESTORE_TEST
        executadas: list[date] = []

        dia = date(2027, 1, 1)
        while dia < date(2028, 1, 1):
            if deve_rodar_restore_test(dia, marcador):
                executadas.append(dia)
                marcador.write_text(competencia(dia), encoding="utf-8")
            dia += timedelta(days=1)

        assert len(executadas) == 12
        assert [d.month for d in executadas] == list(range(1, 13))
        assert {d.month for d in executadas} >= {2, 4, 6, 9, 11}

    def test_ano_bissexto_e_dia_29_nao_confundem_a_competencia(self, tmp_path):
        marcador = tmp_path / "marcador"
        assert deve_rodar_restore_test(date(2028, 2, 29), marcador) is True
        marcador.write_text(competencia(date(2028, 2, 29)), encoding="utf-8")
        assert marcador.read_text(encoding="utf-8") == "2028-02"
        assert deve_rodar_restore_test(date(2028, 2, 29), marcador) is False

    def test_mes_em_que_o_cron_so_voltou_no_dia_9_ainda_e_coberto(self, tmp_path):
        """Nenhum dia é 'o dia': perder oito execuções não perde a competência."""
        marcador = tmp_path / "marcador"
        marcador.write_text("2027-02", encoding="utf-8")
        assert deve_rodar_restore_test(date(2027, 3, 9), marcador) is True

    def test_execucoes_repetidas_no_mesmo_dia_nao_repetem_o_teste(self, tmp_path):
        marcador = tmp_path / "marcador"
        hoje = date(2027, 5, 4)
        assert deve_rodar_restore_test(hoje, marcador) is True
        marcador.write_text(competencia(hoje), encoding="utf-8")
        assert deve_rodar_restore_test(hoje, marcador) is False


# ---------------------------------------------------------------------
# Rotinas de shell: backup e restore-test
# ---------------------------------------------------------------------


@pytest.fixture()
def script_registrado(monkeypatch):
    """Substitui `rodar_script` por um espião que sempre passa.

    Registra também o `timeout_s`. O espião ACEITAVA o parâmetro e o descartava,
    e um espião que aceita tudo em silêncio não prova nada: o teto de tempo
    podia sumir da chamada sem que um teste sequer piscasse — e é ele que
    impede um `pg_dump` travado de segurar o contêiner de cron para sempre,
    fazendo a rotina parar de rodar sem nunca ter falhado.
    """
    chamadas: list[tuple[str, list[str], int]] = []

    def falso(caminho, argumentos, *, timeout_s):
        chamadas.append((Path(caminho).name, [str(a) for a in argumentos], timeout_s))
        return {"script": Path(caminho).name, "codigo": 0, "saida": ">> OK"}

    monkeypatch.setattr(rotinas, "rodar_script", falso)
    return chamadas


@pytest.fixture()
def script_quebrado(monkeypatch):
    """Substitui `rodar_script` por um que sempre falha."""

    def falso(caminho, argumentos, *, timeout_s):
        raise RotinaError(f"{Path(caminho).name} saiu com código 1: disco cheio")

    monkeypatch.setattr(rotinas, "rodar_script", falso)


class TestBackup:
    def test_chama_o_script_com_o_diretorio_de_destino(self, tmp_path, script_registrado):
        detalhe = executar_backup(scripts_dir=tmp_path / "scripts", backup_dir=tmp_path / "bkp")

        assert script_registrado == [("backup.sh", [str(tmp_path / "bkp")], TIMEOUT_BACKUP_S)]
        assert detalhe["diretorio"] == str(tmp_path / "bkp")
        assert detalhe["codigo"] == 0

    def test_falha_do_script_vira_excecao(self, tmp_path, script_quebrado):
        with pytest.raises(RotinaError, match="disco cheio"):
            executar_backup(scripts_dir=tmp_path, backup_dir=tmp_path)


class TestRestoreTest:
    def test_primeira_execucao_do_mes_roda_e_marca_a_competencia(self, tmp_path, script_registrado):
        detalhe = executar_restore_test(date(2027, 3, 9), scripts_dir=tmp_path, backup_dir=tmp_path)

        assert detalhe["executado"] is True
        assert detalhe["competencia"] == "2027-03"
        assert detalhe["marcador_gravado"] is True
        assert script_registrado == [("restore_test.sh", [str(tmp_path)], TIMEOUT_RESTORE_TEST_S)]
        assert (tmp_path / rotinas.MARCADOR_RESTORE_TEST).read_text(
            encoding="utf-8"
        ).strip() == "2027-03"

    def test_segunda_execucao_no_mesmo_mes_nao_chama_o_script(self, tmp_path, script_registrado):
        executar_restore_test(date(2027, 3, 9), scripts_dir=tmp_path, backup_dir=tmp_path)
        detalhe = executar_restore_test(
            date(2027, 3, 25), scripts_dir=tmp_path, backup_dir=tmp_path
        )

        assert detalhe["executado"] is False
        assert detalhe["motivo"] == "competencia_ja_coberta"
        assert len(script_registrado) == 1

    def test_mes_seguinte_roda_de_novo(self, tmp_path, script_registrado):
        executar_restore_test(date(2027, 3, 9), scripts_dir=tmp_path, backup_dir=tmp_path)
        detalhe = executar_restore_test(date(2027, 4, 1), scripts_dir=tmp_path, backup_dir=tmp_path)

        assert detalhe["executado"] is True
        assert detalhe["competencia"] == "2027-04"
        assert len(script_registrado) == 2

    def test_forcar_ignora_a_competencia_ja_coberta(self, tmp_path, script_registrado):
        executar_restore_test(date(2027, 3, 9), scripts_dir=tmp_path, backup_dir=tmp_path)
        detalhe = executar_restore_test(
            date(2027, 3, 10), scripts_dir=tmp_path, backup_dir=tmp_path, forcar=True
        )

        assert detalhe["executado"] is True
        assert len(script_registrado) == 2

    def test_falha_nao_marca_a_competencia_e_e_retentada_no_dia_seguinte(
        self, tmp_path, script_quebrado
    ):
        """Um backup que não restaura precisa insistir todo dia até passar."""
        with pytest.raises(RotinaError):
            executar_restore_test(date(2027, 3, 9), scripts_dir=tmp_path, backup_dir=tmp_path)

        assert not (tmp_path / rotinas.MARCADOR_RESTORE_TEST).exists()
        assert deve_rodar_restore_test(date(2027, 3, 10), tmp_path / rotinas.MARCADOR_RESTORE_TEST)

    def test_marcador_ingravavel_nao_falha_a_rotina(self, tmp_path, script_registrado):
        """O teste PASSOU; não poder anotar isso é desperdício, não risco."""
        destino = tmp_path / "bkp"
        destino.mkdir()
        (destino / rotinas.MARCADOR_RESTORE_TEST).mkdir()  # ocupa o nome com um diretório

        detalhe = executar_restore_test(date(2027, 3, 9), scripts_dir=tmp_path, backup_dir=destino)

        assert detalhe["executado"] is True
        assert detalhe["marcador_gravado"] is False


class TestRodarScript:
    def test_script_ausente_e_falha_com_mensagem_acionavel(self, tmp_path):
        with pytest.raises(RotinaError) as exc:
            rodar_script(tmp_path / "nao_existe.sh", [], timeout_s=5)

        mensagem = str(exc.value)
        assert "nao_existe.sh" in mensagem
        assert "ORGCRED_SCRIPTS_DIR" in mensagem

    @sem_bash
    def test_codigo_zero_devolve_a_saida(self, tmp_path):
        script = tmp_path / "ok.sh"
        script.write_text("#!/usr/bin/env bash\necho '>> feito'\n", encoding="utf-8")

        detalhe = rodar_script(script, [], timeout_s=30)

        assert detalhe["codigo"] == 0
        assert ">> feito" in detalhe["saida"]

    @sem_bash
    def test_codigo_diferente_de_zero_vira_excecao_com_o_stderr(self, tmp_path):
        script = tmp_path / "falha.sh"
        script.write_text(
            "#!/usr/bin/env bash\necho 'ERRO: sem espaco em disco' >&2\nexit 3\n",
            encoding="utf-8",
        )

        with pytest.raises(RotinaError) as exc:
            rodar_script(script, [], timeout_s=30)

        assert "código 3" in str(exc.value)
        assert "sem espaco em disco" in str(exc.value)

    @sem_bash
    def test_argumentos_chegam_ao_script(self, tmp_path):
        script = tmp_path / "eco.sh"
        script.write_text('#!/usr/bin/env bash\necho "recebi:$1"\n', encoding="utf-8")

        detalhe = rodar_script(script, ["/var/backups"], timeout_s=30)

        assert "recebi:/var/backups" in detalhe["saida"]

    @sem_bash
    def test_script_travado_e_interrompido_pelo_teto_de_tempo(self, tmp_path):
        """O teto de tempo existe; existir só conta se ele INTERROMPER de fato.

        Um `pg_dump` que trava (rede que não fecha, réplica que não responde)
        sem teto efetivo segura o contêiner de cron: a execução do dia seguinte
        nunca começa e a rotina passa a não rodar SEM NUNCA TER FALHADO — o pior
        estado possível, porque não há linha vermelha para alguém ver.

        O TESTE COBRA O RELÓGIO, e é por isso que ele encontrou um defeito real.
        Verificar só que a exceção sobe passaria com o código antigo, que usava
        `subprocess.run(timeout=...)`: a exceção subia, sim, mas depois dos 30
        segundos inteiros do `sleep` — o `run` mata o bash e volta a esperar os
        netos, que ainda seguram os canos. O teto não limitava tempo nenhum. Um
        teste sem cronômetro teria dado esse comportamento por bom.
        """
        script = tmp_path / "travado.sh"
        script.write_text("#!/usr/bin/env bash\nsleep 30\n", encoding="utf-8")

        inicio = time.monotonic()
        with pytest.raises(RotinaError) as exc:
            rodar_script(script, [], timeout_s=1)
        decorrido = time.monotonic() - inicio

        assert "travado.sh" in str(exc.value)
        assert "1s" in str(exc.value)
        # Folga generosa para máquina de CI carregada, e ainda assim MUITO
        # abaixo dos 30s do script: o que se afirma é que ele foi cortado.
        assert decorrido < 15, f"o teto não interrompeu nada: levou {decorrido:.1f}s"

    @sem_bash
    def test_neto_do_script_tambem_morre_no_teto(self, tmp_path):
        """Não basta o executor voltar: o `pg_dump` tem de PARAR.

        O script inicia um neto que sobreviveria a um `kill` no pai e deixa
        rastro em disco enquanto viver. Depois do teto, o rastro tem de parar de
        crescer — senão o dump continua consumindo conexão e I/O do banco de
        produção depois de a rotina já ter sido dada como falha, e a execução do
        dia seguinte encontra o de hoje ainda rodando.
        """
        marca = tmp_path / "neto.txt"
        script = tmp_path / "com_neto.sh"
        script.write_text(
            "#!/usr/bin/env bash\n"
            f'( for i in $(seq 1 60); do echo x >> "{marca.as_posix()}"; sleep 0.2; done ) &\n'
            "sleep 30\n",
            encoding="utf-8",
        )

        with pytest.raises(RotinaError):
            rodar_script(script, [], timeout_s=2)

        assert marca.is_file(), "cenário mal montado: o neto nem chegou a rodar"
        tamanho = marca.stat().st_size
        time.sleep(1.5)
        assert marca.stat().st_size == tamanho, "o neto continuou vivo depois do teto"


class TestCaminhos:
    """Onde as rotinas procuram scripts e gravam backups.

    Os dois caminhos são configuráveis por ambiente porque o layout do
    contêiner não é o do repositório — e o de backups, em particular, é o que
    decide se o dump cai num volume persistente ou num diretório efêmero que
    morre com o contêiner. Nesse segundo caso o backup é escrito, some, e o log
    diz que concluiu — porque concluiu mesmo. Variável documentada em
    docs/OPERACAO.md e sem teste é variável que um refactor apaga em silêncio.
    """

    def test_backup_dir_vem_do_ambiente(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ORGCRED_BACKUP_DIR", str(tmp_path / "volume"))
        assert diretorio_de_backups() == tmp_path / "volume"

    def test_backup_dir_sem_variavel_cai_no_default(self, monkeypatch):
        monkeypatch.delenv("ORGCRED_BACKUP_DIR", raising=False)
        assert diretorio_de_backups() == Path("./backups")

    def test_backup_dir_vazio_ou_em_branco_cai_no_default(self, monkeypatch):
        """Variável setada com string vazia é o default do painel, não escolha."""
        monkeypatch.setenv("ORGCRED_BACKUP_DIR", "   ")
        assert diretorio_de_backups() == Path("./backups")

    def test_scripts_dir_vem_do_ambiente(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ORGCRED_SCRIPTS_DIR", str(tmp_path / "sh"))
        assert diretorio_de_scripts() == tmp_path / "sh"

    def test_scripts_dir_default_acha_os_scripts_do_repositorio(self, monkeypatch):
        """O default tem de apontar para scripts/ DE VERDADE, não para um palpite."""
        monkeypatch.delenv("ORGCRED_SCRIPTS_DIR", raising=False)
        destino = diretorio_de_scripts()
        assert (destino / "backup.sh").is_file()
        assert (destino / "restore_test.sh").is_file()


# ---------------------------------------------------------------------
# Executor: uma falha não derruba as outras, e o código de saída
# ---------------------------------------------------------------------


def _rotina_ok(nome: str, registro: list[str], detalhe: dict[str, Any] | None = None) -> Rotina:
    def corpo() -> dict[str, Any]:
        registro.append(nome)
        return detalhe or {"feito": nome}

    return Rotina(nome, corpo)


def _rotina_quebrada(nome: str, registro: list[str]) -> Rotina:
    def corpo() -> dict[str, Any]:
        registro.append(nome)
        raise RotinaError(f"{nome} explodiu")

    return Rotina(nome, corpo)


@pytest.mark.usefixtures("logging_isolado")
class TestExecutarRotinas:
    def test_roda_todas_na_ordem_do_plano(self):
        configure_logging(level=logging.INFO, stream=io.StringIO())
        registro: list[str] = []

        resultados = executar_rotinas(
            [_rotina_ok("a", registro), _rotina_ok("b", registro), _rotina_ok("c", registro)]
        )

        assert registro == ["a", "b", "c"]
        assert [r.nome for r in resultados] == ["a", "b", "c"]
        assert all(r.ok for r in resultados)

    def test_falha_no_meio_nao_impede_as_seguintes(self):
        """O caso que motiva o executor: backup quebrado não cancela a régua."""
        configure_logging(level=logging.INFO, stream=io.StringIO())
        registro: list[str] = []

        resultados = executar_rotinas(
            [
                _rotina_quebrada("aging", registro),
                _rotina_quebrada("backup", registro),
                _rotina_ok("restore_test", registro),
            ]
        )

        assert registro == ["aging", "backup", "restore_test"]
        assert [r.ok for r in resultados] == [False, False, True]

    def test_resultado_da_falha_carrega_tipo_e_mensagem(self):
        configure_logging(level=logging.INFO, stream=io.StringIO())

        (resultado,) = executar_rotinas([_rotina_quebrada("backup", [])])

        assert resultado.ok is False
        assert resultado.erro is not None
        assert "RotinaError" in resultado.erro
        assert "backup explodiu" in resultado.erro
        assert resultado.detalhe == {}

    def test_excecao_inesperada_tambem_e_capturada(self):
        """Qualquer exceção, não só RotinaError — o executor não pode presumir."""
        configure_logging(level=logging.INFO, stream=io.StringIO())

        def corpo() -> dict[str, Any]:
            return {"n": 1 / 0}

        (resultado,) = executar_rotinas([Rotina("divisao", corpo)])

        assert resultado.ok is False
        assert "ZeroDivisionError" in (resultado.erro or "")

    def test_interrupcao_do_operador_nao_e_engolida(self):
        """`KeyboardInterrupt` é pedido de parada, não falha de rotina."""
        configure_logging(level=logging.INFO, stream=io.StringIO())

        def corpo() -> dict[str, Any]:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            executar_rotinas([Rotina("interrompida", corpo)])

    def test_mede_a_duracao_de_cada_rotina(self):
        """`>= 0.0` seria satisfeito por um zero fixo — ou seja, por não medir.

        A duração é o que denuncia o `pg_dump` que passou de 40s para 20min ao
        longo de meses, antes de ele estourar o teto de tempo. Por isso a
        cobrança é de um número MAIOR que zero, sobre uma rotina que
        comprovadamente demorou.
        """
        configure_logging(level=logging.INFO, stream=io.StringIO())

        def demorada() -> dict[str, Any]:
            time.sleep(0.02)
            return {"ok": True}

        (resultado,) = executar_rotinas([Rotina("lenta", demorada)])

        assert resultado.duracao_s > 0.0

    def test_mede_a_duracao_tambem_quando_a_rotina_falha(self):
        """Quanto tempo ela levou para falhar separa timeout de recusa imediata."""
        configure_logging(level=logging.INFO, stream=io.StringIO())

        def demorada_e_quebrada() -> dict[str, Any]:
            time.sleep(0.02)
            raise RotinaError("estourou depois de trabalhar")

        (resultado,) = executar_rotinas([Rotina("lenta", demorada_e_quebrada)])

        assert resultado.ok is False
        assert resultado.duracao_s > 0.0

    def test_log_estruturado_por_rotina(self):
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)

        executar_rotinas([_rotina_ok("backup", [], {"arquivos": 3})])

        eventos = _linhas(buffer)
        assert [e["event"] for e in eventos] == ["rotina_iniciada", "rotina_concluida"]
        concluida = eventos[1]
        assert concluida["rotina"] == "backup"
        assert concluida["detalhe"] == {"arquivos": 3}
        assert isinstance(concluida["duracao_s"], float)

    def test_log_de_falha_carrega_traceback(self):
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)

        executar_rotinas([_rotina_quebrada("backup", [])])

        falha = _linhas(buffer)[-1]
        assert falha["event"] == "rotina_falhou"
        assert falha["level"] == "error"
        assert falha["rotina"] == "backup"
        assert "RotinaError" in falha["exception"]

    def test_detalhe_da_rotina_nao_sobrescreve_a_identificacao_da_linha(self):
        """`detalhe` vai aninhado justamente para isto."""
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)

        executar_rotinas([_rotina_ok("backup", [], {"rotina": "impostor", "duracao_s": 999})])

        concluida = _linhas(buffer)[-1]
        assert concluida["rotina"] == "backup"
        assert concluida["duracao_s"] != 999


# ---------------------------------------------------------------------
# Plano do dia
# ---------------------------------------------------------------------


class _SessaoFalsa:
    def __init__(self) -> None:
        self.fechada = False

    def close(self) -> None:
        self.fechada = True


class TestPlano:
    def test_ordem_regua_varredura_backup_restore(self, tmp_path):
        plano = montar_plano(date(2027, 3, 9), scripts_dir=tmp_path, backup_dir=tmp_path)

        assert [r.nome for r in plano] == [
            NOME_AGING,
            NOME_ATIPICIDADES,
            NOME_BACKUP,
            NOME_RESTORE_TEST,
        ]

    def test_apenas_filtra_preservando_a_ordem(self, tmp_path):
        plano = montar_plano(
            date(2027, 3, 9),
            apenas=[NOME_BACKUP, NOME_AGING],
            scripts_dir=tmp_path,
            backup_dir=tmp_path,
        )

        assert [r.nome for r in plano] == [NOME_AGING, NOME_BACKUP]

    def test_apenas_vazio_mantem_o_plano_completo(self, tmp_path):
        plano = montar_plano(date(2027, 3, 9), apenas=[], scripts_dir=tmp_path, backup_dir=tmp_path)
        assert len(plano) == 4

    def test_sessao_e_fechada_mesmo_quando_a_rotina_falha(self):
        sessao = _SessaoFalsa()

        def corpo(_db):
            raise RotinaError("falhou dentro da sessão")

        with pytest.raises(RotinaError):
            rotinas._com_sessao(lambda: sessao, corpo)

        assert sessao.fechada is True

    def test_sessao_e_fechada_no_caminho_feliz(self):
        sessao = _SessaoFalsa()

        assert rotinas._com_sessao(lambda: sessao, lambda _db: {"ok": True}) == {"ok": True}
        assert sessao.fechada is True

    def test_cada_rotina_de_banco_abre_a_propria_sessao(self, monkeypatch, tmp_path):
        """Uma sessão por rotina: erro de uma não deixa a conexão da outra suja."""
        abertas: list[_SessaoFalsa] = []

        def factory():
            sessao = _SessaoFalsa()
            abertas.append(sessao)
            return sessao

        monkeypatch.setattr(rotinas, "executar_aging", lambda db: {"transicionadas": 0})
        monkeypatch.setattr(rotinas, "executar_atipicidades", lambda db: {"novas_ocorrencias": 0})

        plano = montar_plano(
            date(2027, 3, 9),
            apenas=[NOME_AGING, NOME_ATIPICIDADES],
            sessao_factory=factory,
            scripts_dir=tmp_path,
            backup_dir=tmp_path,
        )
        for rotina in plano:
            rotina.executar()

        assert len(abertas) == 2
        assert all(s.fechada for s in abertas)


# ---------------------------------------------------------------------
# Entrypoint: `python -m app.rotinas`
# ---------------------------------------------------------------------


@pytest.mark.usefixtures("logging_isolado")
class TestMain:
    def test_sai_zero_quando_todas_passam(self, monkeypatch, capsys):
        monkeypatch.setattr(
            rotinas, "montar_plano", lambda *a, **k: [_rotina_ok("a", []), _rotina_ok("b", [])]
        )
        assert main([]) == 0

    def test_sai_um_quando_qualquer_uma_falha(self, monkeypatch, capsys):
        """O sinal que faz o Railway marcar a execução como falha."""
        monkeypatch.setattr(
            rotinas,
            "montar_plano",
            lambda *a, **k: [_rotina_ok("a", []), _rotina_quebrada("backup", [])],
        )
        assert main([]) == 1

    def test_uma_falha_isolada_nao_apaga_o_sucesso_das_outras(self, monkeypatch, capsys):
        registro: list[str] = []
        monkeypatch.setattr(
            rotinas,
            "montar_plano",
            lambda *a, **k: [
                _rotina_quebrada("backup", registro),
                _rotina_ok("aging", registro),
            ],
        )

        assert main([]) == 1
        assert registro == ["backup", "aging"]

    def test_resumo_final_nomeia_as_falhas(self, monkeypatch, capsys):
        """Lido de STDOUT, não de um buffer injetado.

        `main` chama `configure_logging()` sem argumento — é o caminho de
        produção, e ele aponta para stdout, que é de onde o Railway agrega. Um
        teste que injetasse buffer provaria o log de um caminho que ninguém
        roda.
        """
        monkeypatch.setattr(
            rotinas,
            "montar_plano",
            lambda *a, **k: [_rotina_ok("aging", []), _rotina_quebrada("backup", [])],
        )

        main(["--data", "2027-03-09"])

        resumo = _saida_estruturada(capsys)[-1]
        assert resumo["event"] == "rotinas_concluidas_com_falha"
        assert resumo["level"] == "error"
        assert resumo["falhas"] == ["backup"]
        assert resumo["total"] == 2
        assert resumo["data"] == "2027-03-09"

    def test_resumo_de_sucesso_nao_lista_falha(self, monkeypatch, capsys):
        monkeypatch.setattr(rotinas, "montar_plano", lambda *a, **k: [_rotina_ok("aging", [])])

        main([])

        resumo = _saida_estruturada(capsys)[-1]
        assert resumo["event"] == "rotinas_concluidas"
        assert resumo["falhas"] == []

    def test_repassa_apenas_data_e_forcar_ao_plano(self, monkeypatch, capsys):
        capturado: dict[str, Any] = {}

        def plano_falso(hoje, *, apenas=None, forcar_restore_test=False, **kwargs):
            capturado.update(hoje=hoje, apenas=apenas, forcar=forcar_restore_test)
            return []

        monkeypatch.setattr(rotinas, "montar_plano", plano_falso)

        codigo = main(["--apenas", NOME_BACKUP, "--data", "2027-03-09", "--forcar-restore-test"])

        assert codigo == 0
        assert capturado == {
            "hoje": date(2027, 3, 9),
            "apenas": [NOME_BACKUP],
            "forcar": True,
        }

    def test_sem_data_usa_hoje(self, monkeypatch, capsys):
        capturado: dict[str, Any] = {}

        def plano_falso(hoje, **kwargs):
            capturado["hoje"] = hoje
            return []

        monkeypatch.setattr(rotinas, "montar_plano", plano_falso)
        main([])

        assert capturado["hoje"] == date.today()

    def test_rotina_desconhecida_e_recusada_na_linha_de_comando(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--apenas", "faxina_inexistente"])
        assert exc.value.code == 2


# ---------------------------------------------------------------------
# Idempotência contra Postgres real
# ---------------------------------------------------------------------


@pytest.fixture()
def sessao_como_no_cron(db_session: Session):
    """Fábrica de sessões que o executor pode abrir, usar e FECHAR de verdade.

    POR QUE ISTO PRECISA EXISTIR. Todo teste de banco desta suíte recebe
    `db_session`, uma sessão que vive dentro de uma transação externa revertida
    no fim (ver tests/conftest.py). Passar essa sessão direto para
    `executar_atipicidades` prova o SQL, mas não prova o que o cron depende:
    `_com_sessao` FECHA a sessão assim que a rotina retorna, e fechar sem
    commit descarta tudo. Uma rotina sem commit passaria por esse teste,
    registraria `novas_ocorrencias: 7` no log, sairia com código 0 — e não
    teria gravado nada. É o silêncio exato que este módulo existe para acabar.

    A fábrica devolve sessões IRMÃS, na mesma conexão física da do teste, com o
    mesmo `join_transaction_mode="create_savepoint"`: cada uma abre o próprio
    SAVEPOINT, o commit da rotina o LIBERA (o dado passa a existir para quem
    olha pela conexão) e o `close()` sem commit REVERTE até ele (o dado some).
    A diferença entre commitar e não commitar fica visível — que é o ponto — e
    o rollback da transação externa continua limpando tudo no fim do teste.
    """
    return sessionmaker(bind=db_session.get_bind(), join_transaction_mode="create_savepoint")


def _criar_ativa_atrasada(db_session: Session, tomador_id: uuid.UUID, dias: int) -> uuid.UUID:
    """Operação ativa com a primeira parcela vencida há `dias`."""
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 2.5, 'PRICE', 12, 'registrada', 'REG-ROTINAS')
        returning id
        """),
        {"t": str(tomador_id)},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)

    # Vencimento é imutável (OC009): o trigger sai do caminho só para fabricar
    # o cenário. `current_date` do BANCO, não `date.today()` do Python — os
    # relógios divergem em três horas e a contagem de atraso sairia por um.
    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    db_session.execute(
        text("""
        update parcela set vencimento = current_date - cast(:dias as int)
        where operacao_id = :id and numero = 1
        """),
        {"dias": dias, "id": str(op_id)},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()
    return op_id


def _contar_eventos(db_session: Session, op_id: uuid.UUID) -> int:
    return db_session.execute(
        text("select count(*) from operacao_evento where operacao_id = :id"),
        {"id": str(op_id)},
    ).scalar_one()


class TestAgingContraBanco:
    def test_transiciona_quem_passou_do_limite(
        self, db_session, tomador_autorizado, capital_constituido
    ):
        op_id = _criar_ativa_atrasada(db_session, tomador_autorizado, dias=120)

        detalhe = executar_aging(db_session)

        assert detalhe["transicionadas"] == 1
        assert detalhe["limite_dias"] == 90
        status = db_session.execute(
            text("select status from operacao_credito where id = :id"), {"id": str(op_id)}
        ).scalar_one()
        assert status == "inadimplente"

    def test_segunda_passada_no_mesmo_dia_nao_duplica_evento(
        self, db_session, tomador_autorizado, capital_constituido
    ):
        """Idempotência da migration 008, exercida pelo caminho do cron."""
        op_id = _criar_ativa_atrasada(db_session, tomador_autorizado, dias=120)

        executar_aging(db_session)
        eventos_apos_primeira = _contar_eventos(db_session, op_id)

        detalhe = executar_aging(db_session)

        assert detalhe["transicionadas"] == 0
        assert _contar_eventos(db_session, op_id) == eventos_apos_primeira

    def test_respeita_limite_customizado(self, db_session, tomador_autorizado, capital_constituido):
        _criar_ativa_atrasada(db_session, tomador_autorizado, dias=45)

        assert executar_aging(db_session)["transicionadas"] == 0
        assert executar_aging(db_session, limite_dias=30)["transicionadas"] == 1

    def test_inadimplencia_sobrevive_ao_fechamento_da_sessao(
        self, db_session, sessao_como_no_cron, tomador_autorizado, capital_constituido
    ):
        """A régua roda pelo caminho REAL do cron — `_com_sessao` — e persiste.

        Declarar inadimplência tem efeito jurídico e reputacional para o
        tomador. Uma régua que reporta `transicionadas: 3` e perde as três no
        fechamento da sessão é pior do que uma régua que falha: ela produz um
        log verde afirmando um ato que nunca aconteceu, e o painel de cobrança
        continua mostrando as operações como `ativa`.
        """
        op_id = _criar_ativa_atrasada(db_session, tomador_autorizado, dias=120)

        detalhe = rotinas._com_sessao(sessao_como_no_cron, executar_aging)

        assert detalhe["transicionadas"] == 1
        # Lido FORA da sessão que a rotina usou e fechou.
        status = db_session.execute(
            text("select status from operacao_credito where id = :id"), {"id": str(op_id)}
        ).scalar_one()
        assert status == "inadimplente"


def _criar_fracionadas(db_session: Session, tomador_id: uuid.UUID, quantas: int = 3) -> None:
    """Operações pequenas do mesmo tomador que somam acima do limiar padrão."""
    for _ in range(quantas):
        db_session.execute(
            text("""
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status)
            values (:t, 'emprestimo', 4000, 2.5, 'PRICE', 6, 'registrada')
            """),
            {"t": str(tomador_id)},
        )
    db_session.commit()


class TestAtipicidadesContraBanco:
    def test_detecta_fracionamento(self, db_session, tomador_autorizado):
        _criar_fracionadas(db_session, tomador_autorizado)

        detalhe = executar_atipicidades(db_session)

        assert detalhe["novas_ocorrencias"] >= 1
        assert detalhe["limiar"] == "10000"
        assert detalhe["janela_dias"] == 30

    def test_segunda_varredura_no_mesmo_dia_nao_duplica_ocorrencia(
        self, db_session, tomador_autorizado
    ):
        """Idempotência das migrations 010/023 (`on conflict do nothing`)."""
        _criar_fracionadas(db_session, tomador_autorizado)
        executar_atipicidades(db_session)
        total_apos_primeira = db_session.execute(
            text("select count(*) from ocorrencia_atipicidade")
        ).scalar_one()

        detalhe = executar_atipicidades(db_session)

        assert detalhe["novas_ocorrencias"] == 0
        assert (
            db_session.execute(text("select count(*) from ocorrencia_atipicidade")).scalar_one()
            == total_apos_primeira
        )

    def test_parametros_customizados_chegam_a_funcao(self, db_session, tomador_autorizado):
        from decimal import Decimal

        _criar_fracionadas(db_session, tomador_autorizado)

        detalhe = executar_atipicidades(db_session, limiar=Decimal("100000"), janela_dias=7)

        assert detalhe["limiar"] == "100000"
        assert detalhe["janela_dias"] == 7
        # Limiar de R$ 100.000 não é atingido por três operações de R$ 4.000.
        assert detalhe["novas_ocorrencias"] == 0

    def test_ocorrencias_sobrevivem_ao_fechamento_da_sessao(
        self, db_session, sessao_como_no_cron, tomador_autorizado
    ):
        """A varredura roda pelo caminho REAL do cron — `_com_sessao` — e persiste.

        Sem o commit, a varredura acharia o fracionamento, contaria a
        ocorrência, devolveria o número para o log, e o `close()` do executor
        jogaria tudo fora. O cron sairia 0, o resumo diria `falhas: []`, e a
        tela de compliance continuaria vazia — que o analista lê como "não há o
        que ver". Um controle de PLD que perde o que detecta é pior que
        controle nenhum, porque produz a impressão de cobertura.
        """
        _criar_fracionadas(db_session, tomador_autorizado)
        antes = db_session.execute(text("select count(*) from ocorrencia_atipicidade")).scalar_one()

        detalhe = rotinas._com_sessao(sessao_como_no_cron, executar_atipicidades)

        assert detalhe["novas_ocorrencias"] >= 1
        depois = db_session.execute(
            text("select count(*) from ocorrencia_atipicidade")
        ).scalar_one()
        assert depois == antes + detalhe["novas_ocorrencias"]

    def test_terceira_varredura_tambem_nao_duplica(self, db_session, tomador_autorizado):
        """Idempotência CONTADA em três passadas, não em duas.

        Duas passadas provam que a segunda não duplica. Uma regra que gravasse
        a cada passada ÍMPAR passaria nesse teste — e o `on conflict do
        nothing` das três regras da 010/023 precisa valer para sempre, não para
        a próxima execução.
        """
        _criar_fracionadas(db_session, tomador_autorizado)

        primeira = executar_atipicidades(db_session)["novas_ocorrencias"]
        total = db_session.execute(text("select count(*) from ocorrencia_atipicidade")).scalar_one()

        assert primeira >= 1
        for _ in range(2):
            assert executar_atipicidades(db_session)["novas_ocorrencias"] == 0
            assert (
                db_session.execute(text("select count(*) from ocorrencia_atipicidade")).scalar_one()
                == total
            )


# ---------------------------------------------------------------------
# Registro da execução na trilha (migration 025)
# ---------------------------------------------------------------------
# O QUE ESTA SEÇÃO PRECISA PROVAR, em ordem de gravidade:
#
# 1. QUE GRAVAR NÃO É PRÉ-REQUISITO DE RODAR. Se o banco estiver fora, o
#    backup — que é `pg_dump` contra o servidor, e pode concluir sem que a
#    aplicação consiga abrir sessão — tem que continuar acontecendo. A
#    escrituração falha, a rotina não.
# 2. QUE SUCESSO E FALHA CHEGAM À TRILHA, contra Postgres real. Uma falha que
#    não é registrada devolve o sistema ao silêncio que a 025 veio acabar.
# 3. QUE A TRILHA NÃO SE EDITA: UPDATE, DELETE e TRUNCATE recusados (OC023).
# 4. QUE O CARIMBO É DO BANCO. É o campo de que a resposta "há quanto tempo"
#    depende inteira; ditá-lo pela aplicação faria "em dia" ser auto-declarado.


class TestResultadoParaTrilha:
    def test_sucesso(self):
        resultado = Resultado(NOME_AGING, True, 1.0, {"transicionadas": 3})
        assert resultado_para_trilha(resultado) == RESULTADO_SUCESSO

    def test_falha(self):
        resultado = Resultado(NOME_BACKUP, False, 1.0, erro="boom")
        assert resultado_para_trilha(resultado) == RESULTADO_FALHA

    def test_executado_false_vira_dispensada(self):
        """O restore-test em dia de folga não é sucesso — ver migration 025."""
        resultado = Resultado(
            NOME_RESTORE_TEST, True, 0.01, {"executado": False, "motivo": "competencia_ja_coberta"}
        )
        assert resultado_para_trilha(resultado) == RESULTADO_DISPENSADA

    def test_executado_true_e_sucesso_normal(self):
        resultado = Resultado(NOME_RESTORE_TEST, True, 300.0, {"executado": True})
        assert resultado_para_trilha(resultado) == RESULTADO_SUCESSO


@pytest.mark.usefixtures("logging_isolado")
class TestExecutorRegistra:
    def test_grava_uma_linha_por_rotina_do_plano(self, trilha_em_memoria):
        configure_logging(level=logging.INFO, stream=io.StringIO())

        executar_rotinas([_rotina_ok("aging", []), _rotina_quebrada("backup", [])])

        assert [r.nome for r in trilha_em_memoria] == ["aging", "backup"]
        assert [r.ok for r in trilha_em_memoria] == [True, False]

    def test_falha_ao_gravar_nao_derruba_a_rotina(self):
        """O caso do enunciado: banco fora, backup ainda tem que rodar.

        A rotina rodou e concluiu; só a escrituração não foi. O `Resultado`
        continua verde — porque o backup existe — e o código de saída do
        processo não muda por causa da anotação.
        """
        configure_logging(level=logging.INFO, stream=io.StringIO())
        registro: list[str] = []

        resultados = executar_rotinas(
            [_rotina_ok("backup", registro)], registrar=lambda _resultado: False
        )

        assert registro == ["backup"]
        assert [r.ok for r in resultados] == [True]

    def test_falha_ao_gravar_nao_e_silenciosa(self):
        """Não gravar é uma notícia, e ela nomeia a consequência.

        Sem esta linha o operador veria o painel dizer "backup atrasado" no dia
        seguinte a um backup que existe, sem nada no log ligando as duas
        coisas.
        """
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)

        executar_rotinas([_rotina_ok("backup", [])], registrar=lambda _resultado: False)

        eventos = {linha["event"]: linha for linha in _linhas(buffer)}
        assert "execucao_nao_registrada" in eventos
        assert eventos["execucao_nao_registrada"]["rotina"] == "backup"
        assert "ATRASADA" in eventos["execucao_nao_registrada"]["consequencia"]

    def test_main_continua_saindo_zero_quando_so_o_registro_falha(self, monkeypatch, capsys):
        """O código de saída responde sobre as ROTINAS, não sobre a anotação.

        Sair 1 aqui mandaria o operador investigar, de madrugada, um backup que
        deu certo.
        """
        monkeypatch.setattr(rotinas, "montar_plano", lambda *a, **k: [_rotina_ok("backup", [])])
        monkeypatch.setattr(rotinas, "registrar_execucao_no_banco", lambda _resultado: False)

        assert main([]) == 0


@pytest.mark.usefixtures("logging_isolado")
class TestRegistrarExecucaoNoBanco:
    """Chama a função IMPORTADA, não `rotinas.registrar_execucao_no_banco`.

    O nome importado no topo deste módulo aponta para a função original e não
    é afetado pelo `monkeypatch` da fixture `trilha_em_memoria` — que é o que
    permite testar aqui o caminho real enquanto o resto do arquivo roda sem
    banco.
    """

    def test_banco_fora_devolve_false_sem_levantar(self):
        """Sessão que nem abre: é o cenário "Postgres indisponível"."""
        configure_logging(level=logging.INFO, stream=io.StringIO())

        def fabrica_quebrada() -> Session:
            raise OSError("connection refused")

        ok = registrar_execucao_no_banco(
            Resultado(NOME_BACKUP, True, 1.0, {"script": "backup.sh"}),
            sessao_factory=fabrica_quebrada,
        )

        assert ok is False

    def test_insert_recusado_devolve_false_e_fecha_a_sessao(self):
        """Sessão abre e o INSERT explode — migration 025 não aplicada, por exemplo.

        A sessão é fechada mesmo no caminho de erro: uma conexão vazada por
        execução acumularia até o pool acabar, e as rotinas passariam a falhar
        por causa do mecanismo que só deveria anotá-las.
        """
        configure_logging(level=logging.INFO, stream=io.StringIO())

        class SessaoQueRecusa:
            def __init__(self) -> None:
                self.fechada = False

            def execute(self, *_a: Any, **_k: Any) -> Any:
                raise RuntimeError('relation "execucao_rotina" does not exist')

            def close(self) -> None:
                self.fechada = True

        sessoes: list[SessaoQueRecusa] = []

        def fabrica() -> Session:
            sessao = SessaoQueRecusa()
            sessoes.append(sessao)
            return sessao  # type: ignore[return-value]

        ok = registrar_execucao_no_banco(Resultado(NOME_AGING, True, 1.0), sessao_factory=fabrica)

        assert ok is False
        assert [s.fechada for s in sessoes] == [True]


def _execucoes(db_session: Session, rotina: str) -> list[Any]:
    return db_session.execute(
        text("""
        select rotina, resultado, duracao_s, detalhe, erro, registrada_em
          from execucao_rotina where rotina = :r order by registrada_em
        """),
        {"r": rotina},
    ).all()


class TestTrilhaContraBanco:
    def test_sucesso_grava_detalhe_e_nao_grava_erro(self, db_session):
        registrar_execucao(
            db_session,
            Resultado(NOME_AGING, True, 1.25, {"transicionadas": 3, "limite_dias": 90}),
        )

        (linha,) = _execucoes(db_session, NOME_AGING)
        assert linha.resultado == RESULTADO_SUCESSO
        assert float(linha.duracao_s) == pytest.approx(1.25)
        assert linha.detalhe == {"transicionadas": 3, "limite_dias": 90}
        assert linha.erro is None

    def test_falha_grava_a_mensagem(self, db_session):
        registrar_execucao(
            db_session,
            Resultado(NOME_BACKUP, False, 12.5, erro="RotinaError: backup.sh saiu com código 2"),
        )

        (linha,) = _execucoes(db_session, NOME_BACKUP)
        assert linha.resultado == RESULTADO_FALHA
        assert "backup.sh saiu com código 2" in linha.erro

    def test_falha_com_mensagem_vazia_ainda_entra_na_trilha(self, db_session):
        """O CHECK exige texto em 'falha'; a falha não pode sumir por causa disso.

        Uma exceção com `str()` vazio existe, e sem o fallback ela viraria
        violação de constraint — a FALHA desapareceria da trilha justamente por
        causa da forma da mensagem, no pior momento possível.
        """
        registrar_execucao(db_session, Resultado(NOME_BACKUP, False, 1.0, erro="   "))

        (linha,) = _execucoes(db_session, NOME_BACKUP)
        assert linha.resultado == RESULTADO_FALHA
        assert linha.erro

    def test_dispensada_grava_o_motivo(self, db_session):
        registrar_execucao(
            db_session,
            Resultado(
                NOME_RESTORE_TEST,
                True,
                0.002,
                {"executado": False, "motivo": "competencia_ja_coberta", "competencia": "2027-03"},
            ),
        )

        (linha,) = _execucoes(db_session, NOME_RESTORE_TEST)
        assert linha.resultado == RESULTADO_DISPENSADA
        assert linha.detalhe["motivo"] == "competencia_ja_coberta"

    def test_detalhe_com_valor_nao_serializavel_nao_derruba_o_registro(self, db_session):
        """Um Decimal no detalhe não pode custar a linha da trilha."""
        registrar_execucao(
            db_session, Resultado(NOME_ATIPICIDADES, True, 0.5, {"limiar": Decimal("10000.50")})
        )

        (linha,) = _execucoes(db_session, NOME_ATIPICIDADES)
        assert linha.detalhe == {"limiar": "10000.50"}

    def test_carimbo_e_do_banco_e_sobrescreve_o_que_o_insert_passar(self, db_session):
        """Sem isto, "rotina em dia" seria auto-declaração.

        Quem tivesse INSERT poderia gravar uma execução datada de agora sem
        rotina nenhuma ter rodado — ou uma antiga com data de hoje, para apagar
        um atraso do painel.
        """
        db_session.execute(
            text("""
            insert into execucao_rotina (rotina, resultado, duracao_s, registrada_em)
            values (:r, 'sucesso', 1, timestamptz '2020-01-01 00:00:00+00')
            """),
            {"r": NOME_AGING},
        )
        db_session.commit()

        (linha,) = _execucoes(db_session, NOME_AGING)
        assert linha.registrada_em.year >= 2026

    def test_update_e_recusado_com_oc023(self, db_session):
        registrar_execucao(db_session, Resultado(NOME_AGING, True, 1.0))

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("update execucao_rotina set resultado = 'sucesso' where rotina = :r"),
                {"r": NOME_AGING},
            )
        assert sqlstate_de(exc.value) == "OC023"
        db_session.rollback()

    def test_delete_e_recusado_com_oc023(self, db_session):
        registrar_execucao(db_session, Resultado(NOME_BACKUP, False, 1.0, erro="x"))

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("delete from execucao_rotina where rotina = :r"), {"r": NOME_BACKUP}
            )
        assert sqlstate_de(exc.value) == "OC023"
        db_session.rollback()

    def test_truncate_e_recusado_com_oc023(self, db_session):
        """TRUNCATE não visita linhas e atravessaria as guardas acima.

        É o caminho pelo qual o histórico inteiro voltaria a não existir — com
        a tela dizendo "nunca executou" e ninguém sabendo por quê.
        """
        registrar_execucao(db_session, Resultado(NOME_AGING, True, 1.0))

        with pytest.raises(Exception) as exc:
            db_session.execute(text("truncate table execucao_rotina"))
        assert sqlstate_de(exc.value) == "OC023"
        db_session.rollback()

    def test_sucesso_com_erro_preenchido_e_recusado(self, db_session):
        """O outro lado do CHECK: erro em execução bem-sucedida só pode ser lixo."""
        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                insert into execucao_rotina (rotina, resultado, duracao_s, erro)
                values (:r, 'sucesso', 1, 'sobrou de uma retentativa')
                """),
                {"r": NOME_AGING},
            )
        assert sqlstate_de(exc.value) == "23514"
        db_session.rollback()

    def test_falha_sem_erro_e_recusada(self, db_session):
        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                insert into execucao_rotina (rotina, resultado, duracao_s)
                values (:r, 'falha', 1)
                """),
                {"r": NOME_BACKUP},
            )
        assert sqlstate_de(exc.value) == "23514"
        db_session.rollback()

    def test_execucao_sobrevive_ao_fechamento_da_sessao(self, db_session, sessao_como_no_cron):
        """Pelo caminho REAL do cron: sessão própria, aberta, commitada e fechada.

        Sem o commit, o executor registraria a execução, o log diria que
        gravou, e o `close()` jogaria a linha fora — o painel continuaria
        mostrando a rotina como parada enquanto ela roda todo dia.
        """
        ok = registrar_execucao_no_banco(
            Resultado(NOME_AGING, True, 2.0, {"transicionadas": 0}),
            sessao_factory=sessao_como_no_cron,
        )

        assert ok is True
        assert len(_execucoes(db_session, NOME_AGING)) == 1


# ---------------------------------------------------------------------
# Estado das rotinas: GET /api/auditoria/rotinas
# ---------------------------------------------------------------------
# O que estes testes cobram é O CÁLCULO DO ATRASO, não a listagem. A rotina que
# nunca falhou e parou de rodar há nove dias não produz nenhuma execução
# vermelha — só uma distância que cresce sozinha, e é ela que a leitura precisa
# enxergar.


@pytest.fixture()
def client_rotinas(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador", papel="operador", ativo=True
    )
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: operador
    yield TestClient(app)
    app.dependency_overrides.clear()


def _estado(client: TestClient) -> dict[str, Any]:
    resposta = client.get("/api/auditoria/rotinas")
    assert resposta.status_code == 200
    return resposta.json()


def _da(corpo: dict[str, Any], nome: str) -> dict[str, Any]:
    return next(r for r in corpo["rotinas"] if r["rotina"] == nome)


class TestEstadoDasRotinas:
    def test_sem_autenticacao_retorna_401(self, db_session):
        def _override_get_db() -> Generator[Session, None, None]:
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db
        try:
            assert TestClient(app).get("/api/auditoria/rotinas").status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_trilha_vazia_marca_as_quatro_como_nunca_executadas(self, client_rotinas):
        """Fail-closed: sem evidência, o sistema NÃO se declara saudável.

        É o estado de um cron que nunca foi implantado — e o único default que
        não deixa esse caso verde para sempre.
        """
        corpo = _estado(client_rotinas)

        assert corpo["saudavel"] is False
        assert sorted(r["rotina"] for r in corpo["rotinas"]) == sorted(ROTINAS_CONHECIDAS)
        for nome in ROTINAS_CONHECIDAS:
            estado = _da(corpo, nome)
            assert estado["nunca_executou"] is True
            assert estado["atrasada"] is True
            assert estado["horas_desde_ultimo_sucesso"] is None

    def test_as_quatro_recem_executadas_ficam_saudaveis(self, client_rotinas, db_session):
        for nome in ROTINAS_CONHECIDAS:
            registrar_execucao(db_session, Resultado(nome, True, 1.0, {"ok": True}))

        corpo = _estado(client_rotinas)

        assert corpo["saudavel"] is True
        for nome in ROTINAS_CONHECIDAS:
            estado = _da(corpo, nome)
            assert estado["atrasada"] is False
            assert estado["falhou"] is False
            assert estado["horas_desde_ultimo_sucesso"] == pytest.approx(0, abs=0.1)
            assert estado["limite_horas"] == LIMITE_ATRASO_HORAS[nome]

    def test_diaria_a_trinta_horas_ainda_nao_e_atraso(self, client_rotinas, db_session):
        """O limiar NÃO é 24h, e este teste é a razão.

        Um cron diário que começa alguns minutos depois do de ontem já
        ultrapassaria 24h. Um aviso que dispara por construção é um aviso que
        as pessoas desligam — e a partir daí o atraso real fica indistinguível
        do ruído.
        """
        registrar_execucao(db_session, Resultado(NOME_AGING, True, 1.0))
        envelhecer_execucao_rotina(db_session, NOME_AGING, horas=30)

        estado = _da(_estado(client_rotinas), NOME_AGING)

        assert estado["horas_desde_ultimo_sucesso"] == pytest.approx(30, abs=0.1)
        assert estado["atrasada"] is False

    def test_diaria_parada_ha_nove_dias_e_atraso(self, client_rotinas, db_session):
        """O caso perigoso do enunciado: nunca falhou, parou de rodar.

        Não há execução vermelha em lugar nenhum — só a distância.
        """
        for nome in ROTINAS_CONHECIDAS:
            registrar_execucao(db_session, Resultado(nome, True, 1.0))
        envelhecer_execucao_rotina(db_session, NOME_AGING, horas=9 * 24)

        corpo = _estado(client_rotinas)
        estado = _da(corpo, NOME_AGING)

        assert estado["falhou"] is False
        assert estado["atrasada"] is True
        assert estado["horas_desde_ultimo_sucesso"] == pytest.approx(216, abs=0.1)
        assert corpo["saudavel"] is False

    def test_ultima_execucao_falhada_aparece_com_a_mensagem(self, client_rotinas, db_session):
        registrar_execucao(db_session, Resultado(NOME_BACKUP, True, 60.0))
        registrar_execucao(
            db_session, Resultado(NOME_BACKUP, False, 3.0, erro="RotinaError: disco cheio")
        )

        corpo = _estado(client_rotinas)
        estado = _da(corpo, NOME_BACKUP)

        assert estado["falhou"] is True
        assert estado["resultado"] == RESULTADO_FALHA
        assert "disco cheio" in estado["erro"]
        # O relógio de atraso continua ancorado no ÚLTIMO SUCESSO, e não na
        # última tentativa: uma rotina que falha todo dia tem tentativa recente
        # e não fez o trabalho nenhuma vez.
        assert estado["ultimo_sucesso"] is not None
        assert corpo["saudavel"] is False

    def test_falha_repetida_acaba_virando_atraso_tambem(self, client_rotinas, db_session):
        """Falhar sem parar é, passado o limiar, a mesma coisa que não rodar."""
        registrar_execucao(db_session, Resultado(NOME_BACKUP, True, 60.0))
        envelhecer_execucao_rotina(db_session, NOME_BACKUP, horas=48)
        registrar_execucao(
            db_session, Resultado(NOME_BACKUP, False, 3.0, erro="RotinaError: disco cheio")
        )

        estado = _da(_estado(client_rotinas), NOME_BACKUP)

        assert estado["falhou"] is True
        assert estado["atrasada"] is True

    def test_dispensada_nao_renova_o_relogio_do_restore_test(self, client_rotinas, db_session):
        """A razão de 'dispensada' existir como resultado próprio.

        O restore-test é dispensado em ~30 dos 31 dias do mês. Contadas como
        sucesso, essas linhas diriam "restore-test em dia" todo santo dia sobre
        um teste de restauração que não acontece há quase dois meses.
        """
        registrar_execucao(db_session, Resultado(NOME_RESTORE_TEST, True, 300.0))
        envelhecer_execucao_rotina(db_session, NOME_RESTORE_TEST, horas=50 * 24)
        registrar_execucao(
            db_session,
            Resultado(NOME_RESTORE_TEST, True, 0.01, {"executado": False, "motivo": "coberta"}),
        )

        estado = _da(_estado(client_rotinas), NOME_RESTORE_TEST)

        assert estado["atrasada"] is True
        assert estado["horas_desde_ultimo_sucesso"] == pytest.approx(50 * 24, abs=0.1)
        # E o cron ESTEVE aqui hoje — é o que separa "rotina mensal em dia" de
        # "serviço de cron morto", que sem este campo teriam a mesma aparência.
        assert estado["ultima_tentativa"] > estado["ultima_execucao"]

    def test_so_dispensadas_e_nunca_executou_com_o_cron_vivo(self, client_rotinas, db_session):
        """O caso que o comentário do endpoint nomeia e nenhum teste cobria.

        É REAL e é o pior arranjo possível de sinais: o marcador de competência
        do restore-test vive no VOLUME de backups, e a trilha vive no BANCO.
        Banco novo com volume antigo — restauração, recriação da base, troca de
        instância — deixa o executor achando que a competência já está coberta
        e devolvendo `executado: False` todo santo dia. A trilha enche de
        'dispensada' e o teste de restauração NUNCA acontece.

        Aqui o cron está vivo (há tentativa de hoje) e o trabalho jamais foi
        feito. As duas coisas precisam ser ditas ao mesmo tempo, e é justamente
        a combinação que o endpoint tem de acertar sem nenhuma linha
        'sucesso' nem 'falha' para se apoiar: `ultima_tentativa` preenchida,
        `ultima_execucao` vazia, `nunca_executou` verdadeiro e — o que importa
        — ATRASADA.

        Ler isto como "em dia" devolveria exatamente a cobertura de fachada que
        a migration 025 existe para acabar, agora com registro no banco para
        sustentá-la.
        """
        for nome in (NOME_AGING, NOME_ATIPICIDADES, NOME_BACKUP):
            registrar_execucao(db_session, Resultado(nome, True, 1.0))
        registrar_execucao(
            db_session,
            Resultado(
                NOME_RESTORE_TEST,
                True,
                0.01,
                {"executado": False, "motivo": "competencia_ja_coberta"},
            ),
        )

        corpo = _estado(client_rotinas)
        estado = _da(corpo, NOME_RESTORE_TEST)

        assert estado["ultima_tentativa"] is not None  # o cron esteve aqui
        assert estado["ultima_execucao"] is None  # e não fez o trabalho
        assert estado["nunca_executou"] is True
        assert estado["atrasada"] is True
        assert estado["horas_desde_ultimo_sucesso"] is None
        assert estado["resultado"] is None
        assert estado["erro"] is None
        assert estado["detalhe"] == {}
        assert corpo["saudavel"] is False

    def test_restore_test_a_quarenta_dias_ainda_nao_e_atraso(self, client_rotinas, db_session):
        """O limiar mensal não é 31 dias, e este teste é a razão.

        31 dispararia todo fim de mês por construção, na véspera de a rotina
        rodar. 40 dias é a distância legítima de uma competência cuja primeira
        execução escorregou para o dia 9 — cenário que o executor já tolera de
        propósito (ver `deve_rodar_restore_test`).
        """
        for nome in ROTINAS_CONHECIDAS:
            registrar_execucao(db_session, Resultado(nome, True, 1.0))
        envelhecer_execucao_rotina(db_session, NOME_RESTORE_TEST, horas=40 * 24)

        corpo = _estado(client_rotinas)

        assert _da(corpo, NOME_RESTORE_TEST)["atrasada"] is False
        assert corpo["saudavel"] is True

    def test_inicio_e_derivado_da_duracao(self, client_rotinas, db_session):
        """`iniciada_em` = registrada_em - duracao_s. Não é coluna — ver a 025."""
        registrar_execucao(db_session, Resultado(NOME_BACKUP, True, 600.0))

        estado = _da(_estado(client_rotinas), NOME_BACKUP)

        inicio = datetime.fromisoformat(estado["iniciada_em"])
        fim = datetime.fromisoformat(estado["ultima_execucao"])
        assert (fim - inicio).total_seconds() == pytest.approx(600, abs=1)

    def test_rotina_desconhecida_aparece_e_nao_derruba_a_saude(self, client_rotinas, db_session):
        """A contrapartida de a coluna `rotina` não ter CHECK de domínio.

        Um nome que o executor não conhece é ruído VISÍVEL — melhor do que uma
        trilha que recusa o que deveria testemunhar. Sem limiar declarado ele
        não é dado como atrasado: seria inventar uma periodicidade que ninguém
        prometeu.
        """
        for nome in ROTINAS_CONHECIDAS:
            registrar_execucao(db_session, Resultado(nome, True, 1.0))
        registrar_execucao(db_session, Resultado("faxina_experimental", True, 1.0))

        corpo = _estado(client_rotinas)
        estado = _da(corpo, "faxina_experimental")

        assert estado["limite_horas"] is None
        assert estado["atrasada"] is False
        assert corpo["saudavel"] is True
