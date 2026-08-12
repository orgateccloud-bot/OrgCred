"""Testes de app.core.logging — mascaramento de PII (LGPD) e emissão real.

Os testes de emissão existem porque a pipeline structlog escreve *através* da
stdlib: já esteve completa e mesmo assim silenciosa em produção, por falta de
handler no root logger. Aqui a prova é a linha que sai, não a configuração que
entra.
"""

import io
import json
import logging
from contextlib import contextmanager
from typing import Generator, Iterator

import pytest

from app.core.logging import _HANDLER_NAME, _nivel_padrao, configure_logging, get_logger, mask_pii


class TestMaskPII:
    def test_mascara_cpf_formatado(self) -> None:
        texto = "Tomador com CPF 123.456.789-01 solicitou crédito"
        assert "123.456.789-01" not in mask_pii(texto)
        assert "***.***.***-**" in mask_pii(texto)

    def test_mascara_cnpj_formatado(self) -> None:
        texto = "Empresa CNPJ 12.345.678/0001-99 ativou operação"
        resultado = mask_pii(texto)
        assert "12.345.678/0001-99" not in resultado

    def test_mascara_cpf_sem_formatacao(self) -> None:
        texto = "CPF bruto: 12345678901 no payload"
        resultado = mask_pii(texto)
        assert "12345678901" not in resultado

    def test_nao_mascara_texto_sem_pii(self) -> None:
        texto = "Operação ativada com sucesso, valor R$ 30000.00"
        assert mask_pii(texto) == texto

    def test_nao_mascara_numeros_curtos(self) -> None:
        texto = "Operação 12345 processada"
        assert mask_pii(texto) == texto


@contextmanager
def _estado_de_logging_preservado() -> Iterator[None]:
    """Devolve o root logger ao estado anterior — inclusive o handler da aplicação.

    `configure_logging()` mexe em estado global do processo. Devolver só a
    LISTA de handlers não basta: quando a aplicação já instalou o dela — e ela
    instala, `app.main` chama `configure_logging()` no import, que os módulos
    de teste de router disparam já na coleta —, a chamada seguinte REAPONTA
    aquele mesmo objeto para o stream do teste em vez de criar outro.
    Restaurar apenas a lista devolveria um handler escrevendo num buffer já
    descartado: todo log emitido depois daqui sumiria em silêncio pelo resto
    da suíte, que é exatamente a falha que estes testes existem para impedir.
    """
    root = logging.getLogger()
    handlers = list(root.handlers)
    nivel = root.level

    anterior = next((h for h in handlers if h.get_name() == _HANDLER_NAME), None)
    stream_anterior = anterior.stream if isinstance(anterior, logging.StreamHandler) else None
    nivel_anterior = anterior.level if anterior is not None else None

    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(nivel)
        if isinstance(anterior, logging.StreamHandler) and stream_anterior is not None:
            # Atribuição direta em vez de `setStream()`: aquele dá flush no
            # stream que está saindo, e o que está saindo aqui pode ser o
            # stdout efêmero do `capsys`, já fechado quando o teste terminou
            # (`ValueError: I/O operation on closed file`).
            anterior.stream = stream_anterior
        if anterior is not None and nivel_anterior is not None:
            anterior.setLevel(nivel_anterior)


@pytest.fixture()
def logging_isolado() -> Generator[None, None, None]:
    """Isola o estado global de logging do teste — ver `_estado_de_logging_preservado`."""
    with _estado_de_logging_preservado():
        yield


def _linhas(buffer: io.StringIO) -> list[str]:
    """Linhas não vazias escritas no buffer."""
    return [linha for linha in buffer.getvalue().splitlines() if linha.strip()]


@pytest.mark.usefixtures("logging_isolado")
class TestEmissao:
    def test_info_produz_linha_json(self) -> None:
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)

        get_logger("teste.emissao").info("app_startup", environment="test")

        linhas = _linhas(buffer)
        assert len(linhas) == 1
        # A linha inteira é o JSON: se o formatter da stdlib acrescentasse
        # prefixo, aqui apareceria timestamp/nível duplicado antes do '{'.
        assert linhas[0].startswith("{") and linhas[0].endswith("}")

        registro = json.loads(linhas[0])
        assert registro["event"] == "app_startup"
        assert registro["level"] == "info"
        assert registro["logger"] == "teste.emissao"
        assert registro["environment"] == "test"
        assert "timestamp" in registro

    def test_configurar_duas_vezes_nao_duplica_saida(self) -> None:
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)
        configure_logging(level=logging.INFO, stream=buffer)

        get_logger("teste.idempotencia").info("evento_unico")

        assert len(_linhas(buffer)) == 1

    def test_configurar_duas_vezes_nao_duplica_handler(self) -> None:
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)
        configure_logging(level=logging.INFO, stream=buffer)

        nossos = [h for h in logging.getLogger().handlers if h.get_name() == _HANDLER_NAME]
        assert len(nossos) == 1

    def test_nivel_info_descarta_debug(self) -> None:
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)
        logger = get_logger("teste.nivel")

        logger.debug("nao_deve_aparecer")
        logger.info("deve_aparecer")

        linhas = _linhas(buffer)
        assert len(linhas) == 1
        assert json.loads(linhas[0])["event"] == "deve_aparecer"

    def test_nivel_debug_deixa_passar_debug(self) -> None:
        buffer = io.StringIO()
        configure_logging(level=logging.DEBUG, stream=buffer)

        get_logger("teste.nivel.debug").debug("evento_debug")

        assert json.loads(_linhas(buffer)[0])["event"] == "evento_debug"

    def test_erro_com_excecao_vira_campo_no_json(self) -> None:
        """Rastro de exceção não tratada — o caso que motivou a correção."""
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)

        try:
            raise ValueError("falha inesperada")
        except ValueError:
            get_logger("teste.excecao").exception("erro_nao_tratado", codigo="OC001")

        registro = json.loads(_linhas(buffer)[0])
        assert registro["event"] == "erro_nao_tratado"
        assert registro["level"] == "error"
        assert registro["codigo"] == "OC001"
        assert "ValueError" in registro["exception"]

    def test_pii_mascarada_na_linha_emitida(self) -> None:
        buffer = io.StringIO()
        configure_logging(level=logging.INFO, stream=buffer)

        get_logger("teste.pii").warning("bloqueio_sqlstate", documento="123.456.789-01")

        registro = json.loads(_linhas(buffer)[0])
        assert registro["documento"] == "***.***.***-**"
        assert "123.456.789-01" not in _linhas(buffer)[0]

    def test_saida_padrao_e_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Sem `stream`, a saída vai para stdout — é dele que o Railway lê."""
        configure_logging(level=logging.INFO)

        get_logger("teste.stdout").info("evento_stdout")

        capturado = capsys.readouterr()
        assert capturado.err == ""
        assert json.loads(capturado.out.strip())["event"] == "evento_stdout"

    def test_chamada_de_producao_sem_argumento_emite(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`app.main` chama `configure_logging()` sem argumento nenhum.

        Os demais testes passam `level`/`stream`; é este caminho — o único que
        roda em produção — que precisa produzir linha.
        """
        configure_logging()

        get_logger("teste.producao").info("evento_producao")

        assert json.loads(capsys.readouterr().out.strip())["event"] == "evento_producao"


@pytest.mark.usefixtures("logging_isolado")
class TestIsolamentoDeEstado:
    """O próprio isolamento é comportamento testado: sem ele, este arquivo
    silencia o log da aplicação para todos os testes que rodam depois."""

    def _instalar_handler_da_aplicacao(self, stream: io.StringIO) -> logging.Handler:
        """Reproduz o handler que `app.main` deixa no root ao ser importado.

        Os já existentes com o mesmo nome saem da lista de propósito:
        `configure_logging()` reaproveita o PRIMEIRO que encontrar, e o teste
        precisa saber qual objeto está observando.
        """
        root = logging.getLogger()
        root.handlers[:] = [h for h in root.handlers if h.get_name() != _HANDLER_NAME]
        handler = logging.StreamHandler(stream)
        handler.set_name(_HANDLER_NAME)
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        return handler

    def test_restaura_stream_e_nivel_do_handler_da_aplicacao(self) -> None:
        stream_da_app = io.StringIO()
        da_app = self._instalar_handler_da_aplicacao(stream_da_app)

        with _estado_de_logging_preservado():
            configure_logging(level=logging.DEBUG, stream=io.StringIO())
            # Pré-condição: é mesmo o handler da aplicação que foi reapontado,
            # e não um segundo handler empilhado ao lado dele.
            assert da_app.stream is not stream_da_app
            assert da_app.level == logging.DEBUG

        assert da_app.stream is stream_da_app
        assert da_app.level == logging.INFO

    def test_aplicacao_volta_a_registrar_depois_do_isolamento(self) -> None:
        """Prova de ponta a ponta: a linha volta a cair no stream da aplicação."""
        stream_da_app = io.StringIO()
        self._instalar_handler_da_aplicacao(stream_da_app)
        configure_logging(level=logging.INFO, stream=stream_da_app)

        with _estado_de_logging_preservado():
            configure_logging(level=logging.INFO, stream=io.StringIO())

        get_logger("teste.apos_isolamento").info("volta_para_a_aplicacao")

        assert json.loads(_linhas(stream_da_app)[0])["event"] == "volta_para_a_aplicacao"


class TestNivelPadrao:
    """`configure_logging()` sem argumento deriva o nível de `settings.debug`."""

    def test_debug_ligado_usa_debug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core import config

        monkeypatch.setattr(config.settings, "debug", True)
        assert _nivel_padrao() == logging.DEBUG

    def test_debug_desligado_usa_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core import config

        monkeypatch.setattr(config.settings, "debug", False)
        assert _nivel_padrao() == logging.INFO
