"""
Executor único das rotinas periódicas do OrgCred.

O PROBLEMA QUE ESTE MÓDULO RESOLVE
----------------------------------
Quatro rotinas existiam e nenhuma era agendada. `scripts/backup.sh` e
`scripts/restore_test.sh` estavam no repositório sem que nada os chamasse. A
régua de aging (`POST /cobranca/aging/processar`) e a varredura de atipicidade
(`POST /compliance/atipicidades/detectar`) só rodavam por CLIQUE — o que
significa que a data em que uma inadimplência era declarada dependia de alguém
lembrar, e que a detecção de PLD acontecia quando desse na telha.

Uma régua de 90 dias que roda no dia 104 declara a inadimplência 14 dias
atrasada, e não há nada no sistema que registre que ela atrasou. Um controle de
PLD que roda por impulso produz uma tela vazia que o analista lê como "não há o
que ver".

A DECISÃO DE INFRA: UM SERVIÇO, UMA AGENDA, UM COMANDO
------------------------------------------------------
Um serviço cron no Railway, uma agenda diária, `python -m app.rotinas`. O QUE
roda em cada dia é decidido AQUI, em código coberto por teste — não em quatro
agendas de painel que ninguém revisa e que divergem em silêncio da realidade do
repositório. Ver `docs/OPERACAO.md`.

AS TRÊS PROPRIEDADES QUE FAZEM ISTO SER CONFIÁVEL
-------------------------------------------------
1. IDEMPOTÊNCIA. Rodar duas vezes no mesmo dia não duplica evento nem
   ocorrência. Isso NÃO é uma propriedade deste módulo — é do banco, e foi
   conferida lendo: `fn_processar_aging` (migration 008) só toca operações em
   'ativa', então a segunda passada não acha nada; `fn_detectar_atipicidades`
   (migrations 010/023) tem `on conflict ... do nothing` no índice único
   `ocorrencia_unica` nas três regras. Aqui só não se estraga isso.

2. UMA FALHA NÃO DERRUBA AS OUTRAS. As rotinas rodam todas, os erros são
   coletados, e só no fim se decide o código de saída. Um backup que falha por
   disco cheio não pode impedir a régua de declarar uma inadimplência — são
   problemas independentes e tratá-los como um só transforma um incidente em
   dois.

3. CÓDIGO DE SAÍDA != 0 EM QUALQUER FALHA. É isto que faz o Railway marcar a
   execução como falha. Sem isso a rotina quebra em silêncio — exatamente o
   problema que este módulo existe para resolver. Um cron que sempre sai 0 é
   pior que cron nenhum, porque produz a impressão de cobertura.
"""

import argparse
import os
import shutil

# B404 (import de subprocess), suprimido na própria linha: chamar shell é o
# ponto — `backup.sh` e `restore_test.sh` encadeiam pg_dump/psql/gzip e não têm
# equivalente em biblioteca padrão. Nenhum argumento vem de entrada não
# confiável, e o comando é sempre uma LISTA, sem shell=True (ver `rodar_script`).
# A justificativa fica FORA do marcador de supressão de propósito: o bandit lê
# tudo que vem depois dele como lista de IDs de teste e avisa a cada palavra.
import signal
import subprocess  # nosec B404
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import IO, Any, Callable, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import processar_aging
from app.core.logging import configure_logging, get_logger
from app.db import SessionLocal

# Os parâmetros de negócio vêm dos MESMOS objetos que os endpoints usam, e não
# de constantes repetidas aqui. Se a ESC decidir que o limite de inadimplência
# passa a ser 120 dias, o botão e o cron mudam juntos — dois números iguais em
# dois arquivos é a forma clássica de a régua automática passar meses decidindo
# por um critério diferente do que a tela mostra.
from app.routers.cobranca import ProcessarAgingIn
from app.routers.compliance import DetectarIn


NOME_AGING = "aging"
NOME_ATIPICIDADES = "atipicidades"
NOME_BACKUP = "backup"
NOME_RESTORE_TEST = "restore_test"

ROTINAS_CONHECIDAS = (NOME_AGING, NOME_ATIPICIDADES, NOME_BACKUP, NOME_RESTORE_TEST)

# Marcador da competência em que o restore-test rodou pela última vez. Fica ao
# lado dos backups de propósito: é o mesmo volume, então ou os dois sobrevivem
# ao restart do contêiner ou nenhum dos dois — e o modo de falha "perdi o
# marcador" (rodar o teste de novo) é infinitamente mais barato que "perdi os
# backups".
MARCADOR_RESTORE_TEST = ".ultimo_restore_test"

# Tetos de tempo. Um pg_dump que trava sem estes números segura o contêiner de
# cron para sempre e a execução do dia seguinte nunca começa — a rotina passa a
# não rodar sem nunca ter falhado, que é o pior estado possível.
TIMEOUT_BACKUP_S = 30 * 60
TIMEOUT_RESTORE_TEST_S = 45 * 60


class RotinaError(RuntimeError):
    """Falha de uma rotina. Coletada pelo executor, nunca aborta as demais."""


@dataclass(frozen=True)
class Rotina:
    """Uma rotina do plano do dia.

    `executar` devolve um dicionário com O QUE ELA FEZ (vai inteiro para o log
    estruturado) e LEVANTA exceção quando falha. Devolver um booleano de
    sucesso seria a porta de entrada do silêncio: quem esquece de checar o
    retorno produz um cron verde sobre uma rotina quebrada.
    """

    nome: str
    executar: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class Resultado:
    """O que aconteceu com uma rotina, já medido."""

    nome: str
    ok: bool
    duracao_s: float
    detalhe: dict[str, Any] = field(default_factory=dict)
    erro: str | None = None


# ---------------------------------------------------------------------
# Onde estão as coisas
# ---------------------------------------------------------------------
# Ambos os caminhos são sobrescritíveis por ambiente porque o layout do
# contêiner de cron não é o do repositório: a imagem de runtime copia `app/`
# para `/app/app/`, e o `scripts/` só existe lá se o Dockerfile o copiar (ver
# docs/OPERACAO.md, "Pré-requisitos do serviço de cron"). Sem a variável, o
# default é o layout do repositório — que é o que vale ao rodar à mão.


def diretorio_de_scripts() -> Path:
    """Onde vivem `backup.sh` e `restore_test.sh`."""
    do_ambiente = os.environ.get("ORGCRED_SCRIPTS_DIR", "").strip()
    if do_ambiente:
        return Path(do_ambiente)
    return Path(__file__).resolve().parent.parent / "scripts"


def diretorio_de_backups() -> Path:
    """Onde os dumps são gravados e de onde o restore-test os lê.

    Precisa ser um volume persistente. Num diretório efêmero o backup é escrito,
    o contêiner morre e o arquivo vai junto — com o log dizendo que o backup
    concluiu, porque ele concluiu mesmo.
    """
    do_ambiente = os.environ.get("ORGCRED_BACKUP_DIR", "").strip()
    if do_ambiente:
        return Path(do_ambiente)
    return Path("./backups")


# ---------------------------------------------------------------------
# A regra mensal do restore-test
# ---------------------------------------------------------------------


def competencia(dia: date) -> str:
    """Competência (`AAAA-MM`) a que um dia pertence."""
    return f"{dia.year:04d}-{dia.month:02d}"


def deve_rodar_restore_test(hoje: date, marcador: Path) -> bool:
    """O restore-test já rodou nesta competência?

    POR QUE NÃO EXISTE DIA FIXO AQUI. O critério óbvio — "roda no dia 1", "roda
    no dia 15" — tem dois modos de falha conhecidos e nenhum deles avisa:

      * DIA QUE NÃO EXISTE. `dia == 31` pula fevereiro, abril, junho, setembro
        e novembro inteiros. O clássico: o teste de restauração some em cinco
        meses do ano e o painel não mostra ausência nenhuma, porque não houve
        execução para falhar.
      * DIA PERDIDO. Qualquer dia fixo é pulado de vez se o cron não rodar
        naquela data — deploy em andamento, serviço reiniciando, incidente. O
        mês inteiro fica sem teste e a próxima chance é daqui a 30 dias.

    O critério real é OUTRA PERGUNTA: "esta competência já teve seu teste?".
    Ela não depende de dia nenhum, então nenhum dia pode ser pulado. Roda na
    PRIMEIRA execução de cada mês, seja ela dia 1 ou dia 9.

    E o marcador só é escrito depois do SUCESSO (ver `executar_restore_test`):
    um teste que falha não marca a competência como coberta e é retentado no
    dia seguinte, todo dia, até passar. Um backup que não restaura é o tipo de
    problema que precisa insistir.

    Marcador ausente ou ilegível => roda. Fail-open aqui é o lado seguro: o
    custo é um teste de restauração a mais, e o custo do outro lado é descobrir
    na hora do desastre que o backup nunca foi testado.

    "Ilegível" são DUAS famílias de erro, e só uma delas é `OSError`. Um arquivo
    com bytes que não são UTF-8 — escrita interrompida pela metade, volume com
    setor corrompido, alguém que apontou a variável para o arquivo errado —
    levanta `UnicodeDecodeError`, que descende de `ValueError`, não de
    `OSError`. Capturar só `OSError` faria o marcador corrompido DERRUBAR a
    rotina em vez de rodá-la: o teste mensal de restauração pararia de
    acontecer, e a linha vermelha diria "UnicodeDecodeError" sobre um arquivo
    de três bytes, a quilômetros do backup que ninguém está mais testando.
    """
    try:
        anterior = marcador.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return True
    return anterior != competencia(hoje)


def _registrar_competencia(marcador: Path, comp: str) -> bool:
    """Grava a competência coberta. Devolve se conseguiu."""
    try:
        marcador.parent.mkdir(parents=True, exist_ok=True)
        marcador.write_text(f"{comp}\n", encoding="utf-8")
    except OSError:
        # Não falha a rotina: o restore-test PASSOU, e essa é a informação que
        # importa. Sem o marcador ele volta a rodar amanhã — desperdício, não
        # risco. Derrubar o cron inteiro por causa disso trocaria um teste
        # repetido por uma execução vermelha que ninguém sabe interpretar.
        return False
    return True


# ---------------------------------------------------------------------
# Execução dos scripts de shell
# ---------------------------------------------------------------------


def _cauda(texto: str, linhas: int = 15) -> str:
    """Últimas linhas não vazias — é onde o erro de um script costuma estar."""
    uteis = [linha for linha in texto.strip().splitlines() if linha.strip()]
    return "\n".join(uteis[-linhas:])


def _decodificar(arquivo: IO[bytes]) -> str:
    """Lê do começo o que o script escreveu, sem deixar o texto virar o erro."""
    arquivo.seek(0)
    return arquivo.read().decode("utf-8", errors="replace")


def _interpretador() -> str:
    """Caminho ABSOLUTO do bash, resolvido pelo PATH.

    E não o literal `"bash"`: no Windows o `CreateProcess` procura em System32
    ANTES do PATH, e lá mora o `bash.exe` do WSL — que não enxerga os caminhos
    do host e falha com uma mensagem sobre relay de processo, três camadas
    longe do problema real. `shutil.which` respeita o PATH e acha o bash que o
    ambiente realmente instalou. Em Linux, onde o executor roda de verdade, os
    dois resolvem para o mesmo `/bin/bash`.

    Ausência de bash é FALHA explícita, não `FileNotFoundError` cru: a diferença
    entre "o shell não está na imagem" e "o script não está na imagem" é a
    primeira coisa que o operador precisa saber.
    """
    caminho = shutil.which("bash")
    if caminho is None:
        raise RotinaError(
            "bash não encontrado no PATH — a imagem do serviço de cron precisa dele "
            "para rodar scripts/backup.sh e scripts/restore_test.sh."
        )
    return caminho


def _encerrar_arvore(processo: "subprocess.Popen[bytes]") -> None:
    """Derruba o script E TUDO que ele iniciou.

    Matar só o processo direto não resolve, e é essa a razão de a função
    existir: `backup.sh` é um bash que encadeia `pg_dump | gzip`. Um `kill` no
    bash deixa os dois netos vivos — e o que trava uma rotina destas nunca é o
    shell, é sempre o `pg_dump` esperando uma resposta do banco que não vem.

    Um dump órfão não é um detalhe estético: ele segue segurando conexão e I/O
    do servidor de produção depois de a rotina já ter sido dada como falha, e é
    justamente numa madrugada de dump travado que ninguém quer o dump do dia
    seguinte começando por cima do de hoje.

    Sem dependência nova: grupo de processos no POSIX, `taskkill /T` no Windows.
    """
    if sys.platform == "win32":
        # /T pega a árvore inteira a partir do PID; /F não negocia. É o
        # equivalente Windows do killpg — não há grupo de processos aqui.
        subprocess.run(  # nosec B603 B607
            ["taskkill", "/F", "/T", "/PID", str(processo.pid)],
            capture_output=True,
            check=False,
        )
    else:
        # `start_new_session=True` fez o script virar líder do próprio grupo,
        # então o sinal alcança os netos sem tocar em quem chamou.
        try:
            os.killpg(os.getpgid(processo.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # morreu entre o estouro do teto e o sinal: já é o que se queria

    try:
        processo.kill()
    except OSError:
        pass  # idem — matar o que já morreu não é erro aqui

    # Recolhe o processo direto para não deixar zumbi. Com teto próprio e
    # curto: se nem depois do SIGKILL ele sair, esperar mais não vai ajudar, e
    # travar AQUI reintroduziria exatamente o bloqueio de que se está saindo.
    try:
        processo.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def rodar_script(caminho: Path, argumentos: Sequence[str], *, timeout_s: int) -> dict[str, Any]:
    """Roda um script de shell e traduz o resultado dele para o mundo Python.

    `bash <caminho>` em vez de executar o arquivo direto: o bit de execução não
    sobrevive a checkout no Windows nem a alguns formatos de cópia de imagem, e
    um `Permission denied` intermitente é péssimo diagnóstico para uma rotina
    que roda de madrugada.

    Script ausente é FALHA, nunca "pulado". Foi assim que estas rotinas
    chegaram até aqui sem nunca terem sido chamadas — a ausência não fazia
    barulho.
    """
    if not caminho.is_file():
        raise RotinaError(
            f"script não encontrado: {caminho}. Verifique se a imagem do serviço de "
            "cron copia o diretório scripts/ (ver docs/OPERACAO.md) ou aponte "
            "ORGCRED_SCRIPTS_DIR para onde ele está."
        )

    comando = [_interpretador(), str(caminho), *argumentos]

    # SAÍDA EM ARQUIVO TEMPORÁRIO, E NÃO EM PIPE. Esta é a diferença que faz o
    # teto de tempo funcionar, e ela foi encontrada por um teste que cronometrou
    # a interrupção em vez de só conferir que a exceção subia.
    #
    # Com `capture_output=True` (ou `stdout=PIPE`), quem segura a ponta de
    # escrita do cano não é só o bash: é também cada NETO que ele iniciou —
    # `pg_dump`, `gzip`, `psql`. Matar o bash não fecha o cano, e a leitura do
    # pai continua bloqueada esperando os netos. Medido: script com `sleep 30`,
    # teto de 1s, `subprocess.run` voltando aos 30,2s. O teto não limitava nada.
    #
    # Com arquivo não há cano, não há thread leitora e não há espera: `wait()`
    # olha só o processo direto, volta no instante do teto, e o que um órfão
    # ainda escreva cai num arquivo que já ninguém lê.
    with tempfile.TemporaryFile() as saida_bruta, tempfile.TemporaryFile() as erro_bruto:
        # B603: lista de argumentos, sem shell=True. `caminho` sai de constantes
        # deste módulo ou de ORGCRED_SCRIPTS_DIR, que é configuração do próprio
        # serviço — quem controla essa variável já controla o processo.
        processo = subprocess.Popen(  # nosec B603
            comando,
            stdout=saida_bruta,
            stderr=erro_bruto,
            # Grupo de processos próprio, para `_encerrar_arvore` ter em que
            # pegar. Ignorado no Windows, onde ela usa taskkill.
            start_new_session=True,
        )

        try:
            processo.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _encerrar_arvore(processo)
            # `RotinaError`, e não `TimeoutExpired` crua: toda falha desta função
            # chega ao executor com a mesma forma e já nomeando o script. O
            # número de segundos entra na mensagem porque é ele que o operador
            # vai querer comparar com a duração das execuções que deram certo.
            raise RotinaError(
                f"{caminho.name} não terminou em {timeout_s}s e foi interrompido, "
                "junto com os processos que havia iniciado (pg_dump/psql/gzip)."
            ) from None

        # `errors="replace"` porque isto é diagnóstico, não dado: um `pg_dump`
        # que devolve mensagem do sistema operacional em latin-1 não pode
        # derrubar a rotina POR CAUSA DA MENSAGEM, escondendo o erro de verdade
        # atrás de um UnicodeDecodeError.
        saida = _decodificar(saida_bruta)
        erro = _decodificar(erro_bruto)

    if processo.returncode != 0:
        raise RotinaError(
            f"{caminho.name} saiu com código {processo.returncode}: "
            f"{_cauda(erro) or _cauda(saida) or '(sem saída)'}"
        )

    return {"script": caminho.name, "codigo": processo.returncode, "saida": _cauda(saida)}


# ---------------------------------------------------------------------
# As quatro rotinas
# ---------------------------------------------------------------------


def executar_aging(db: Session, *, limite_dias: int | None = None) -> dict[str, Any]:
    """Régua de inadimplência: 'ativa' com atraso >= limite passa a 'inadimplente'.

    Mesma função que o endpoint de admin chama (`processar_aging`), com o mesmo
    default — é o ponto todo. As transições ficam na trilha com
    `origem = 'sistema'` e autor nulo, que é o registro honesto: ninguém
    apertou botão nenhum.

    Idempotente pela migration 008: a segunda passada do dia não encontra mais
    nada em 'ativa' acima do limite, devolve zero e não grava evento.
    """
    limite = ProcessarAgingIn().limite_dias if limite_dias is None else limite_dias
    transicionadas = processar_aging(db, limite_dias=limite)
    return {"transicionadas": transicionadas, "limite_dias": limite}


def executar_atipicidades(
    db: Session,
    *,
    limiar: Decimal | None = None,
    janela_dias: int | None = None,
) -> dict[str, Any]:
    """Varredura de atipicidade (PLD) sobre os dados existentes.

    Idempotente pelas migrations 010/023: as três regras gravam com
    `on conflict ... do nothing` contra o índice único `ocorrencia_unica`, e
    desde a 023 nenhuma delas compara nada com `current_date` — a mesma
    varredura devolve o mesmo conjunto hoje e daqui a cinco anos.

    `limiar` sai como string no detalhe porque `Decimal` não é serializável em
    JSON e o renderizador do log resolveria isso do jeito dele, sem contrato.
    """
    padrao = DetectarIn()
    limiar_efetivo = padrao.limiar if limiar is None else limiar
    janela_efetiva = padrao.janela_dias if janela_dias is None else janela_dias

    novas = db.execute(
        text("select fn_detectar_atipicidades(:limiar, :janela)"),
        {"limiar": limiar_efetivo, "janela": janela_efetiva},
    ).scalar_one()
    db.commit()
    return {
        "novas_ocorrencias": int(novas),
        "limiar": str(limiar_efetivo),
        "janela_dias": janela_efetiva,
    }


def executar_backup(*, scripts_dir: Path, backup_dir: Path) -> dict[str, Any]:
    """Dump lógico do banco + rotação de 30 dias, via `scripts/backup.sh`."""
    detalhe = rodar_script(scripts_dir / "backup.sh", [str(backup_dir)], timeout_s=TIMEOUT_BACKUP_S)
    return {"diretorio": str(backup_dir), **detalhe}


def executar_restore_test(
    hoje: date,
    *,
    scripts_dir: Path,
    backup_dir: Path,
    forcar: bool = False,
) -> dict[str, Any]:
    """Restaura o backup mais recente num banco temporário e valida o ledger.

    Um backup nunca restaurado não é backup, é um arquivo. Mensal porque o
    teste restaura o dump INTEIRO — custa tempo e espaço no mesmo servidor onde
    o dado de produção vive, e fazer isso todo dia trocaria um risco por outro.

    Quando não é a vez, devolve `executado: False` COM MOTIVO em vez de sumir do
    plano. A diferença importa às 3h da manhã: o log de todo dia diz por que a
    rotina não rodou, e "não vejo linha nenhuma de restore_test" deixa de ter
    duas leituras possíveis ("não era a vez" e "o executor nem tentou").
    """
    marcador = backup_dir / MARCADOR_RESTORE_TEST
    comp = competencia(hoje)

    if not forcar and not deve_rodar_restore_test(hoje, marcador):
        return {
            "executado": False,
            "motivo": "competencia_ja_coberta",
            "competencia": comp,
        }

    detalhe = rodar_script(
        scripts_dir / "restore_test.sh", [str(backup_dir)], timeout_s=TIMEOUT_RESTORE_TEST_S
    )
    marcado = _registrar_competencia(marcador, comp)
    return {"executado": True, "competencia": comp, "marcador_gravado": marcado, **detalhe}


# ---------------------------------------------------------------------
# Plano do dia
# ---------------------------------------------------------------------


def _com_sessao(
    sessao_factory: Callable[[], Session],
    corpo: Callable[[Session], dict[str, Any]],
) -> dict[str, Any]:
    """Abre uma sessão só para a rotina e a fecha aconteça o que acontecer.

    Uma sessão por rotina, e não uma para o plano inteiro: a régua e a varredura
    dão commit próprio, e compartilhar sessão faria uma exceção da segunda
    encontrar a conexão em estado indefinido deixado pela primeira.
    """
    db = sessao_factory()
    try:
        return corpo(db)
    finally:
        db.close()


def montar_plano(
    hoje: date,
    *,
    apenas: Sequence[str] | None = None,
    sessao_factory: Callable[[], Session] = SessionLocal,
    scripts_dir: Path | None = None,
    backup_dir: Path | None = None,
    forcar_restore_test: bool = False,
) -> list[Rotina]:
    """Monta a lista de rotinas do dia, na ordem em que devem rodar.

    A ORDEM NÃO É ARBITRÁRIA:

      1. régua de aging      — muda estado de operação
      2. varredura de PLD    — lê o estado, inclusive o que a régua acabou de mudar
      3. backup              — captura o dia já processado, não o dia pela metade
      4. restore-test        — valida o backup que ACABOU de ser feito

    Invertida, a sequência produz um backup do estado de ontem e um teste de
    restauração sobre um dump que não é o do dia.

    Todas as quatro entram no plano sempre. O restore-test decide internamente
    se é a vez dele — ver `executar_restore_test`.
    """
    scripts = diretorio_de_scripts() if scripts_dir is None else scripts_dir
    backups = diretorio_de_backups() if backup_dir is None else backup_dir

    plano = [
        Rotina(NOME_AGING, lambda: _com_sessao(sessao_factory, executar_aging)),
        Rotina(NOME_ATIPICIDADES, lambda: _com_sessao(sessao_factory, executar_atipicidades)),
        Rotina(NOME_BACKUP, lambda: executar_backup(scripts_dir=scripts, backup_dir=backups)),
        Rotina(
            NOME_RESTORE_TEST,
            lambda: executar_restore_test(
                hoje,
                scripts_dir=scripts,
                backup_dir=backups,
                forcar=forcar_restore_test,
            ),
        ),
    ]

    if apenas:
        escolhidas = set(apenas)
        plano = [rotina for rotina in plano if rotina.nome in escolhidas]
    return plano


# ---------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------


def executar_rotinas(rotinas: Sequence[Rotina]) -> list[Resultado]:
    """Roda todas as rotinas, coleta os erros, não interrompe por falha.

    O `except Exception` largo é deliberado e é a razão de este executor
    existir: qualquer exceção de uma rotina precisa virar um `Resultado`
    vermelho, não o fim do plano. `BaseException` fica de fora de propósito —
    `KeyboardInterrupt` e `SystemExit` são pedidos de parada e devem parar.
    """
    logger = get_logger("app.rotinas")
    resultados: list[Resultado] = []

    for rotina in rotinas:
        logger.info("rotina_iniciada", rotina=rotina.nome)
        inicio = time.monotonic()
        try:
            detalhe = rotina.executar()
        except Exception as exc:
            duracao = round(time.monotonic() - inicio, 3)
            erro = f"{type(exc).__name__}: {exc}"
            # `.exception()` e não `.error()`: sem o traceback, diagnosticar
            # uma falha de madrugada vira arqueologia sobre uma linha de texto.
            logger.exception("rotina_falhou", rotina=rotina.nome, duracao_s=duracao, erro=erro)
            resultados.append(Resultado(rotina.nome, False, duracao, erro=erro))
        else:
            duracao = round(time.monotonic() - inicio, 3)
            # `detalhe` aninhado, não espalhado com **: uma chave chamada
            # "rotina" ou "duracao_s" vinda de uma rotina sobrescreveria os
            # campos que identificam a linha do log.
            logger.info("rotina_concluida", rotina=rotina.nome, duracao_s=duracao, detalhe=detalhe)
            resultados.append(Resultado(rotina.nome, True, duracao, detalhe=detalhe))

    return resultados


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.rotinas",
        description=(
            "Executor das rotinas periódicas do OrgCred. Sem argumentos roda o "
            "plano do dia — é assim que o serviço de cron o chama."
        ),
    )
    parser.add_argument(
        "--apenas",
        action="append",
        choices=list(ROTINAS_CONHECIDAS),
        metavar="ROTINA",
        help=(
            "Roda só a(s) rotina(s) indicada(s). Repetível. Serve para "
            "reexecutar à mão a que falhou, sem repetir as que já passaram."
        ),
    )
    parser.add_argument(
        "--data",
        type=date.fromisoformat,
        metavar="AAAA-MM-DD",
        help="Data de referência da decisão mensal. Default: hoje.",
    )
    parser.add_argument(
        "--forcar-restore-test",
        action="store_true",
        help="Roda o teste de restauração mesmo que a competência já esteja coberta.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada. Devolve o código de saída do processo.

    ZERO SÓ QUANDO TUDO PASSOU. É este número que o Railway lê para marcar a
    execução como falha e para o alerta disparar; um executor que sempre sai 0
    seria uma rotina quebrando em silêncio com aparência de cobertura, que é
    exatamente o estado do qual estamos saindo.
    """
    configure_logging()
    args = _parse_args(argv)
    logger = get_logger("app.rotinas")

    hoje = args.data or date.today()
    plano = montar_plano(
        hoje,
        apenas=args.apenas,
        forcar_restore_test=args.forcar_restore_test,
    )

    logger.info("plano_montado", data=hoje.isoformat(), rotinas=[r.nome for r in plano])
    resultados = executar_rotinas(plano)

    falhas = [r.nome for r in resultados if not r.ok]
    resumo = {
        "data": hoje.isoformat(),
        "total": len(resultados),
        "falhas": falhas,
        "duracao_total_s": round(sum(r.duracao_s for r in resultados), 3),
    }

    if falhas:
        logger.error("rotinas_concluidas_com_falha", **resumo)
        return 1

    logger.info("rotinas_concluidas", **resumo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
