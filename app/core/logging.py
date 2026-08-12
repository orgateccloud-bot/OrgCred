"""
Logging estruturado com mascaramento de PII (LGPD).

Estruturado via structlog; mascaramento determinístico para CPF/CNPJ.

A pipeline escreve *através* da stdlib (`structlog.stdlib.LoggerFactory`), então
`configure_logging()` também precisa inicializar o `logging` da stdlib: sem
handler no root logger — e com o nível default WARNING — todo `logger.info()`
é descartado silenciosamente e o deploy fica sem rastro de bloqueio por
SQLSTATE, falha de autenticação ou exceção não tratada.
"""

import logging
import re
import sys
from typing import Any, TextIO

import structlog


# Marcador do handler que instalamos no root logger. É o que garante
# idempotência: rechamar configure_logging() reaproveita este handler em vez de
# empilhar outro (o que duplicaria cada linha de log).
_HANDLER_NAME = "orgcred_stdout"


def mask_pii(text: str) -> str:
    """Mascara CPF e CNPJ em texto."""
    # CPF: XXX.XXX.XXX-XX
    text = re.sub(r"\d{3}\.\d{3}\.\d{3}-\d{2}", "***.***.***-**", text)
    # CNPJ: XX.XXX.XXX/XXXX-XX
    text = re.sub(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", "**.***.***/****-**", text)
    # Números soltos (heurística: 11 ou 14 dígitos sem formatação)
    text = re.sub(r"\b\d{11}\b", r"***\*\***\*\***", text)  # CPF
    text = re.sub(r"\b\d{14}\b", r"**\*\***\*\***\*\***", text)  # CNPJ
    return text


class MaskingProcessor:
    """Processador structlog que mascara PII em valores de log."""

    def __call__(self, logger: Any, name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        # Mascara 'message' e 'exc_info'
        if "event" in event_dict:
            event_dict["event"] = mask_pii(str(event_dict["event"]))

        # Mascara qualquer valor string
        for key in list(event_dict.keys()):
            if isinstance(event_dict[key], str):
                event_dict[key] = mask_pii(event_dict[key])

        return event_dict


def _nivel_padrao() -> int:
    """
    Nível de log derivado da configuração da aplicação.

    `app.core.config` não tem campo dedicado de nível; o que existe é `debug`.
    Import local de propósito: mantém o import deste módulo independente da
    validação de startup da config.
    """
    from app.core.config import settings

    return logging.DEBUG if settings.debug else logging.INFO


def configure_logging(level: int | None = None, stream: TextIO | None = None) -> None:
    """
    Configura logging estruturado com structlog e inicializa a stdlib.

    Idempotente: chamar duas vezes não duplica handler nem linha de log — o
    handler existente é reaproveitado (e reapontado para `stream`, útil em
    teste), nunca somado a outro.

    `level` e `stream` existem para teste; em produção o nível vem de
    `settings.debug` e a saída é stdout (agregada pelo Railway).
    """
    nivel = _nivel_padrao() if level is None else level
    saida = sys.stdout if stream is None else stream

    root = logging.getLogger()
    handler = next((h for h in root.handlers if h.get_name() == _HANDLER_NAME), None)
    if handler is None:
        handler = logging.StreamHandler(saida)
        handler.set_name(_HANDLER_NAME)
        # A linha JSON já sai pronta do JSONRenderer do structlog (com
        # timestamp e level dentro dela). O formatter da stdlib só repassa a
        # mensagem — qualquer outro formato duplicaria timestamp e nível.
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
    elif isinstance(handler, logging.StreamHandler):
        handler.setStream(saida)

    handler.setLevel(nivel)
    # `structlog.stdlib.filter_by_level` consulta o logger da stdlib; sem
    # ajustar o root, o nível efetivo continuaria WARNING.
    root.setLevel(nivel)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            MaskingProcessor(),  # type: ignore[list-item]  # PII masking
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Obtém logger estruturado."""
    return structlog.get_logger(name)
