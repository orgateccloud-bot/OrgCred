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
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app import rotinas
from app.capital_engine import ativar_operacao
from app.core.logging import configure_logging
from app.rotinas import (
    NOME_AGING,
    NOME_ATIPICIDADES,
    NOME_BACKUP,
    NOME_RESTORE_TEST,
    TIMEOUT_BACKUP_S,
    TIMEOUT_RESTORE_TEST_S,
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
    rodar_script,
)
from tests.conftest import confirmar_registro
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
